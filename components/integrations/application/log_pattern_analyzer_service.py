"""Deterministic temporal log-pattern analysis — the sensor half of the
log-optimization pipeline.

Same POC hard rule as the error path: **never run an LLM over the raw log
firehose.** This module reads a recent log window, normalizes every line to a
stable ``signature`` (task name / health-check shape, volatile IDs stripped),
and folds the counts into a persistent per-``(connection, signature)`` rollup so
the system reasons about logs *over time* — a pattern is only surfaced when it
is BOTH high-frequency AND sustained across several aggregation runs, never a
one-window blip.

What it surfaces (deterministically): periodic tasks firing far more often than
their value warrants ("``workflow_run_due_schedules`` fired 41× this window —
consider a longer interval"), health-check / housekeeping noise drowning the
stream, and single services dominating log volume. The concrete recommendation
("raise the beat interval from */5 to */10") is left to the optimization agent
(LLM-after-detection); everything here is fact the detector can stand behind.

Bounded-context boundary: the agents-context detector imports ONLY this
application module (never integrations persistence), same as the error path.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from components.integrations.application.log_ingest_service import iter_window_records

logger = logging.getLogger(__name__)

# --- Deterministic thresholds (tuned conservative; the agent adds nuance) -----
# A periodic task must fire at least this many times in one window to be a
# frequency candidate.
PERIODIC_FREQ_THRESHOLD = 6
# Health-check / housekeeping noise must dominate at least this many lines.
HEALTH_NOISE_THRESHOLD = 20
# A single service signature this loud is a volume candidate.
VOLUME_THRESHOLD = 120
# "Sustained over time" — a pattern is only flagged once it has been observed in
# at least this many aggregation runs (blip suppression). Overridable for tests.
DEFAULT_MIN_RUNS = 2

# --- Normalization: strip volatile tokens so the same event shares a signature.
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX_RE = re.compile(r"\b[0-9a-f]{12,}\b", re.I)
_NUM_RE = re.compile(r"\b\d+\b")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?")
_BRACKET_ID_RE = re.compile(r"\[[^\]]*\]")

# celery beat scheduler line: "Sending due task <name> (<dotted.path>)"
_BEAT_RE = re.compile(r"Sending due task\s+(?P<name>[\w.\-]+)\s*\((?P<path>[\w.\-]+)\)")
# HTTP access-log health pings.
_HEALTH_HTTP_RE = re.compile(r"(GET|HEAD)\s+\S*/(health|healthz|ping|readiness|liveness)", re.I)
# Redis / DB housekeeping chatter.
_HOUSEKEEPING_MARKERS = (
    "Background saving",
    "DB saved on disk",
    "Fork CoW",
    "changes in",
    "RDB",
    "Saving...",
)


def _signature(service: str, message: str) -> str:
    """Collapse a log line to a stable signature (volatile tokens removed)."""
    beat = _BEAT_RE.search(message)
    if beat:
        # Periodic tasks key on the task name only — the schedule id/time vary.
        return f"{service}|beat|{beat.group('path') or beat.group('name')}"
    s = _TS_RE.sub("<ts>", message)
    s = _UUID_RE.sub("<uuid>", s)
    s = _HEX_RE.sub("<hex>", s)
    s = _BRACKET_ID_RE.sub("[]", s)
    s = _NUM_RE.sub("<n>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return f"{service}|{s[:180]}"


def _classify(service: str, message: str) -> tuple[str, str]:
    """Return ``(kind, subject)`` for a line.

    ``subject`` is the human anchor (task name / endpoint) used in the signal
    text and the agent's recommendation prompt.
    """
    beat = _BEAT_RE.search(message)
    if beat:
        return "periodic_task", (beat.group("path") or beat.group("name"))
    health = _HEALTH_HTTP_RE.search(message)
    if health:
        return "health_check", health.group(0)
    if any(m in message for m in _HOUSEKEEPING_MARKERS):
        return "health_check", service
    return "volume", service


@dataclass
class OptimizationFinding:
    """An evidence-bearing optimization finding (deterministic half).

    ``recommendation`` / ``suggested_fix`` are intentionally empty — the
    optimization agent (LLM) fills the concrete action. Everything else is
    measured fact.
    """

    fingerprint: str
    service: str
    kind: str
    signature: str
    subject: str
    signal: str
    last_window_count: int
    runs_observed: int
    total_count: int
    peak_window_count: int
    evidence: list[dict] = field(default_factory=list)
    blast_radius: dict = field(default_factory=dict)
    confidence: str = "medium"

    def as_contract(self) -> dict:
        return {
            "signal": self.signal,
            "service": self.service,
            "kind": self.kind,
            "signature": self.signature,
            "subject": self.subject,
            "frequency": {
                "last_window": self.last_window_count,
                "runs_observed": self.runs_observed,
                "total": self.total_count,
                "peak_window": self.peak_window_count,
            },
            "evidence": self.evidence,
            "blast_radius": self.blast_radius,
            "confidence": self.confidence,
            "fingerprint": self.fingerprint,
            # Filled by the optimization agent (LLM-after-detection):
            "probable_cause": "",
            "suggested_fix": "",
            "recommendation": "",
            "triage": {"status": "pending"},
        }


def _threshold_for(kind: str) -> int:
    return {
        "periodic_task": PERIODIC_FREQ_THRESHOLD,
        "health_check": HEALTH_NOISE_THRESHOLD,
        "volume": VOLUME_THRESHOLD,
    }.get(kind, VOLUME_THRESHOLD)


def _signal_text(kind: str, subject: str, window_count: int) -> str:
    if kind == "periodic_task":
        return f"'{subject}' fired {window_count}× in the last window — likely over-scheduled."
    if kind == "health_check":
        return f"Health-check/housekeeping noise from {subject}: {window_count} lines this window."
    return f"{subject} produced {window_count} log lines this window — dominating volume."


def aggregate_workspace_log_patterns(
    workspace_id,
    *,
    max_objects: int = 40,
    min_runs: int = DEFAULT_MIN_RUNS,
    max_findings: int = 10,
) -> list[OptimizationFinding]:
    """Read a recent window, update the persistent rollups, and return the
    optimization findings whose patterns are high-frequency AND sustained.

    Returns ``[]`` when no AWS source is connected. Idempotent at the finding
    layer: the fingerprint is signature-stable, so the AIAction persistence path
    dedupes repeat cards for the same over-scheduled task.
    """

    from infrastructure.persistence.integrations.models import AwsOrganizationConnection, LogPatternRollup

    conn = (
        AwsOrganizationConnection.objects.filter(workspace_id=workspace_id, status="connected")
        .order_by("-created_at")
        .first()
    )
    if conn is None:
        return []

    # 1) Deterministically count this window's signatures.
    counts: dict[str, int] = {}
    meta: dict[str, dict] = {}
    total_lines = 0
    for lr, _key in iter_window_records(conn, max_objects=max_objects, after=""):
        total_lines += 1
        kind, subject = _classify(lr.service, lr.message)
        sig = _signature(lr.service, lr.message)
        counts[sig] = counts.get(sig, 0) + 1
        if sig not in meta:
            meta[sig] = {"service": lr.service, "kind": kind, "subject": subject, "sample": lr.message[:400]}

    # 2) Fold into the persistent rollups (the "over time" memory) and decide
    #    which patterns now clear their threshold AND are sustained.
    findings: list[OptimizationFinding] = []
    for sig, window_count in counts.items():
        m = meta[sig]
        rollup, _created = LogPatternRollup.objects.get_or_create(
            connection=conn,
            signature=sig,
            defaults={
                "workspace_id": workspace_id,
                "service": m["service"],
                "kind": m["kind"],
                "sample_message": m["sample"],
            },
        )
        rollup.total_count += window_count
        rollup.last_window_count = window_count
        rollup.peak_window_count = max(rollup.peak_window_count, window_count)
        rollup.runs_observed += 1
        rollup.kind = m["kind"]
        rollup.service = m["service"]
        if not rollup.sample_message:
            rollup.sample_message = m["sample"]

        threshold = _threshold_for(m["kind"])
        is_candidate = window_count >= threshold and rollup.runs_observed >= min_runs
        if is_candidate:
            rollup.last_flagged_at = datetime.now(UTC)
        rollup.save()

        if not is_candidate:
            continue

        confidence = "high" if (rollup.runs_observed >= min_runs + 1 and window_count >= threshold * 2) else "medium"
        findings.append(
            OptimizationFinding(
                fingerprint="logopt:" + hashlib.sha256(sig.encode()).hexdigest()[:16],
                service=m["service"],
                kind=m["kind"],
                signature=sig,
                subject=m["subject"],
                signal=_signal_text(m["kind"], m["subject"], window_count),
                last_window_count=window_count,
                runs_observed=rollup.runs_observed,
                total_count=rollup.total_count,
                peak_window_count=rollup.peak_window_count,
                evidence=[
                    {"type": "frequency", "detail": f"{window_count} occurrences in the last window"},
                    {"type": "sustained", "detail": f"observed across {rollup.runs_observed} aggregation runs"},
                    {"type": "sample_line", "detail": m["sample"][:300]},
                ],
                blast_radius={
                    "service": m["service"],
                    "kind": m["kind"],
                    "window_records": total_lines,
                    "share_pct": round(100 * window_count / total_lines, 1) if total_lines else 0,
                },
                confidence=confidence,
            )
        )

    # Loudest first; cap the batch.
    findings.sort(key=lambda f: f.last_window_count, reverse=True)
    logger.info(
        "logopt_aggregate workspace_id=%s connection_id=%s window_lines=%s signatures=%s findings=%s",
        workspace_id,
        conn.id,
        total_lines,
        len(counts),
        len(findings),
    )
    return findings[:max_findings]
