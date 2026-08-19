"""Port: read the findings a report is assembled from.

The assembler depends on this interface, not on the ORM. Two adapters implement
it:

- ``infrastructure/repositories/ssot_finding_repository.py`` — **the default**.
  Reads the ``findings`` SSOT (``infrastructure.persistence.findings.models``)
  and joins the board card on as *enrichment*. Every finding the workspace holds
  is a candidate; a finding that never reached the board still appears, marked
  untriaged.
- ``infrastructure/repositories/board_finding_repository.py`` — the original,
  reading ``project.Task`` rows tagged ``source_type`` ``ai.*``. Retained as the
  board-only lens (it can only ever see what the board floor let through).

Why the SSOT is the spine (2026-08-19): the board applies a **severity floor**
(``AI_BOARD_MIN_SEVERITY`` / a source's ``min_severity``, ADR 0019 D4) and some
sources are deliberately SSOT-only (ADR 0021 D4 keeps domain/DNS hygiene off the
board entirely). Reading the board therefore made every low/medium/informational
finding — and whole source classes — structurally invisible to an evidence-grade
deliverable. Board state (assignee, column, triage decision) is genuinely
valuable, so it is kept: it joins on as enrichment rather than gating the read.

── The finding mapping contract ──────────────────────────────────────────

Each entry of :attr:`FindingPage.findings` is a plain mapping (not an entity —
the report context does not own findings) carrying **at least**:

===================  =========================================================
``id``               stable identity for provenance (SSOT finding id / task id)
``title``            one-line finding title
``description``      prose description, ``""`` when absent
``severity``         **first-class** band string — never only in ``metadata``
``status``           lifecycle status (``open`` / ``triaged`` / …)
``source``           the producing pillar (``cloud_posture.prowler``, …)
``source_type``      the board-facing label (``ai.cloud_posture``), ``""`` when
                     the finding never reached the board
``created_at``       the finding's first observation (dedup + ordering)
``first_seen_at``    first observation
``last_seen_at``     most recent observation
``resolved_at``      when it went terminal, or ``None``
``is_sample``        seeded demo data — MUST be labelled wherever rendered
``dedup_key``        stable identity key; when present the assembler dedups on
                     it verbatim instead of the fuzzy title signature
``metadata``         the section-builder payload shape (see
                     ``domain/services/finding_section_builder.py``)
``triage``           board enrichment — see :class:`TriageEnrichment` keys below
===================  =========================================================

``triage`` is a mapping with ``on_board`` (bool), and when on the board:
``task_id``, ``column``, ``team``, ``task_status``, ``triage_status``,
``assignees`` (list of display names). A finding with no board card carries
``{"on_board": False}`` and is rendered **untriaged** — explicitly, not by the
absence of a field.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FindingQuery:
    """The scope of one report's finding read.

    ``since`` / ``until`` describe the period the report covers, and a finding is
    in the window when it was **live at any point inside it** — i.e. it was first
    seen on or before ``until`` and had not been closed before ``since``. That
    single predicate is what answers both questions a periodic report asks
    ("what appeared this period" and "what did we close"); keying off the board
    card's ``created_at`` — as this port used to — could answer neither.
    """

    workspace_id: str
    #: Kind scope: a finding is a candidate when its source starts with any of
    #: these. Empty tuple = every source in the workspace (the pentest default —
    #: a report about "your security posture" should not silently omit a pillar).
    source_prefixes: tuple[str, ...] = ()
    #: Operator-supplied allow-list, narrowing within ``source_prefixes``.
    sources: tuple[str, ...] = ()
    since: datetime | None = None
    until: datetime | None = None
    #: Hard ceiling on rows pulled into memory (perf rule §5). NEVER a silent
    #: cap: the adapter reports ``total_matched`` so truncation is a stated fact.
    limit: int = 500
    include_resolved: bool = False
    include_suppressed: bool = False
    include_sample: bool = True


@dataclass(frozen=True)
class FindingPage:
    """The findings a report may render, plus the accounting for what it may not.

    Everything excluded is **counted**. A report that silently drops findings is
    the failure this port exists to prevent, so the assembler carries these
    numbers into the deliverable and the grounding corpus rather than discarding
    them.
    """

    findings: tuple[Mapping[str, Any], ...] = field(default=())
    #: Findings matching the scope AND the inclusion policy — the honest
    #: denominator. ``total_matched > len(findings)`` means the limit truncated.
    total_matched: int = 0
    #: In scope but deliberately not listed, per the report kind's policy.
    excluded_resolved: int = 0
    excluded_suppressed: int = 0
    excluded_sample: int = 0
    #: Seeded demo findings among ``findings`` — non-zero stamps the deliverable.
    sample_count: int = 0

    @property
    def returned_count(self) -> int:
        return len(self.findings)

    @property
    def truncated_count(self) -> int:
        """Findings that matched but did not fit under ``limit``."""
        return max(0, self.total_matched - len(self.findings))


class FindingSourcePort(abc.ABC):
    """Reads the findings a report pulls, as plain mappings + their accounting."""

    @abc.abstractmethod
    def list_findings(self, query: FindingQuery) -> FindingPage:
        """Return the scoped findings, most-severe first, with their accounting.

        Ordering is **severity-first**, not recency-first: when ``limit`` bites,
        a report must keep its criticals and drop its lows, never the reverse.

        Implementations MUST resolve the whole page — including any board
        enrichment — in a constant number of queries. A per-finding lookup here
        is an N+1 over the entire report (perf rule §1).
        """
        raise NotImplementedError
