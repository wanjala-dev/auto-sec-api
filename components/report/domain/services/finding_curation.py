"""Deterministic finding curation — collapse near-identical findings, cap detail.

The SOC board routinely carries hundreds of near-identical findings: 320 copies
of "ERROR in celery_worker" differing only by task UUID, dozens of "pgbouncer
produced N log lines this window" differing only by N. Dumping every one into a
pentest report produces a 400-page deliverable that reads like a raw log export,
not a curated assessment — and balloons the narrative grounding prompt past the
model's context window.

Two deterministic steps, NO LLM, NO ORM:

1. :func:`dedupe_findings` — group findings that share a *signature* (severity +
   detector + service + a number/UUID-normalised discriminator) and keep ONE
   representative per group, carrying an ``occurrences`` count and first/last
   seen. 417 raw findings collapse to ~50 distinct issues.

2. :func:`select_featured` — decide which deduped findings get a full §4
   technical write-up. Critical/High always do; the rest fill up to a cap. The
   remainder still appear in the §3 Findings Matrix (nothing is hidden) but not
   as verbose sections — the difference between a curated report and a log dump.

Pure domain: no Django, no framework.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from components.report.domain.value_objects.severity import Severity, normalize_band

# The parts that vary between otherwise-identical findings — UUIDs, long hex
# ids, and digit runs (task ids, line counts, ports) — are normalised out so the
# signature collapses the cluster. Order matters: UUID before bare-hex.
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_HEX_RE = re.compile(r"\b[0-9a-f]{12,}\b", re.IGNORECASE)
_NUM_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase and blank out the varying ids/numbers so a cluster collapses."""
    t = (text or "").lower()
    t = _UUID_RE.sub("#", t)
    t = _HEX_RE.sub("#", t)
    t = _NUM_RE.sub("#", t)
    return _WS_RE.sub(" ", t).strip()


@dataclass(frozen=True)
class CuratedFinding:
    """A representative finding + how many raw findings it stands for."""

    finding: Mapping[str, Any]
    occurrences: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None


def finding_signature(finding: Mapping[str, Any]) -> str:
    """The dedup key for a finding.

    Two findings share a signature when they are the same *kind* of problem on
    the same service — same severity band, same detector/action, same service,
    and the same normalised one-line signal (numbers/ids stripped). The signal
    is the stable discriminator; the title carries the varying task-id so it is
    only the last-resort fallback.
    """
    meta = finding.get("metadata") or {}
    payload = meta.get("payload") or {}
    band = normalize_band(meta.get("severity"))
    action = str(meta.get("action_type") or meta.get("detector") or "").strip().lower()
    service = str(payload.get("service") or "").strip().lower()
    discriminator = payload.get("signal") or payload.get("signature") or finding.get("title") or ""
    return f"{band}|{action}|{service}|{_normalize(str(discriminator))}"


def _representative_key(finding: Mapping[str, Any]) -> tuple[int, str]:
    """Pick the representative within a group — most-severe, then title.

    All members of a group share a severity band (it is in the signature), so in
    practice this resolves ties by title for a stable, deterministic choice.
    """
    meta = finding.get("metadata") or {}
    sev = Severity(normalize_band(meta.get("severity")))
    title = str(meta.get("ai_headline") or finding.get("title") or "")
    return (sev.rank, title.lower())


def dedupe_findings(raw: Sequence[Mapping[str, Any]]) -> tuple[CuratedFinding, ...]:
    """Collapse findings sharing a signature into one representative each.

    Deterministic: groups are emitted in first-seen order; the representative is
    the most-severe/first-title member; ``occurrences`` is the group size.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for finding in raw:
        sig = finding_signature(finding)
        if sig not in groups:
            groups[sig] = []
            order.append(sig)
        groups[sig].append(finding)

    curated: list[CuratedFinding] = []
    for sig in order:
        members = groups[sig]
        representative = min(members, key=_representative_key)
        seens = [m.get("created_at") for m in members if m.get("created_at")]
        curated.append(
            CuratedFinding(
                finding=representative,
                occurrences=len(members),
                first_seen=min(seens) if seens else None,
                last_seen=max(seens) if seens else None,
            )
        )
    return tuple(curated)


def select_featured(
    technicals: Sequence[Any],
    *,
    full_detail_bands: Sequence[str],
    max_count: int,
) -> tuple[Any, ...]:
    """Choose which (already severity-sorted) technical findings get a full §4
    section.

    Critical/High (``full_detail_bands``) are ALWAYS fully detailed — a report
    must never bury a high-severity issue in a table. The lower bands then fill
    the remaining slots up to ``max_count``. The result preserves the input
    order and every returned finding keeps its FID, so §3 and §4 stay aligned.
    """
    full_bands = {b.strip().lower() for b in full_detail_bands}
    featured_fids: set[str] = set()
    lower: list[Any] = []
    for tech in technicals:
        if tech.severity.band in full_bands:
            featured_fids.add(tech.fid)
        else:
            lower.append(tech)

    remaining = max(0, int(max_count) - len(featured_fids))
    for tech in lower[:remaining]:
        featured_fids.add(tech.fid)

    return tuple(tech for tech in technicals if tech.fid in featured_fids)
