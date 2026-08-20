"""Assembled-report domain entities — the structured deliverable data.

These frozen dataclasses are the deterministic output of the assembler and the
ground truth the HTML builder renders and the narrative writer narrates over.
They carry NO framework and NO ORM; the assembler maps board findings into them
and the mapper turns them into JSON for persistence + the template context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.report.domain.value_objects.scan_coverage import ScanCoverage
from components.report.domain.value_objects.severity import SEVERITY_ORDER, Severity


@dataclass(frozen=True)
class EvidenceBlock:
    """The terminal-mockup evidence for a finding — request/response/detector
    output pulled verbatim from the finding's own payload. Rendered as the dark
    evidence block. ``lines`` are already-formatted text lines; ``caption`` is
    the one-line takeaway shown in the accent colour at the block's foot."""

    lines: tuple[str, ...] = ()
    caption: str = ""


@dataclass(frozen=True)
class TriageState:
    """What the board knows about a finding — the "here's what we did about it".

    ``on_board`` is FALSE for a finding that never reached the Kanban board (it
    fell under the board's severity floor, or its source is deliberately
    SSOT-only). That is a first-class, rendered fact — **untriaged** — not the
    absence of a field, because a reader must be able to tell "nobody has looked
    at this" apart from "we forgot to print the column".
    """

    on_board: bool = False
    column: str = ""
    team: str = ""
    task_status: str = ""
    triage_status: str = ""
    assignees: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """One-line triage state for the matrix + the technical section."""
        if not self.on_board:
            return "Untriaged"
        stage = self.column or self.triage_status or self.task_status or "On board"
        if self.assignees:
            return f"{stage} — {', '.join(self.assignees)}"
        return f"{stage} — unassigned"


@dataclass(frozen=True)
class TechnicalFinding:
    """One finding's full technical section (§4 of the report)."""

    fid: str  # "F-01"
    title: str
    category: str
    severity: Severity
    affected_asset: str
    description: str
    remediation: tuple[str, ...]  # bullet points
    evidence: EvidenceBlock
    finding_id: str = ""  # the source finding/Task id (provenance; never rendered)
    # How many raw board findings this representative stands for after dedup
    # (1 = unique). Rendered as "observed N times" so a collapsed cluster is
    # honest about its true volume.
    occurrences: int = 1
    # Board enrichment — the finding's triage state, or "Untriaged".
    triage: TriageState = field(default_factory=TriageState)
    # Seeded demo data. Marked per-finding AND stamped on the document, because a
    # report leaves the building and a demo report that reads as real is worse
    # than no report at all.
    is_sample: bool = False

    @property
    def cvss(self) -> float:
        return self.severity.cvss


@dataclass(frozen=True)
class MatrixRow:
    """One row of the §3 findings matrix."""

    fid: str
    category: str
    title: str
    severity: Severity
    occurrences: int = 1  # raw findings collapsed into this row (1 = unique)
    triage: TriageState = field(default_factory=TriageState)
    is_sample: bool = False

    @property
    def cvss(self) -> float:
        return self.severity.cvss


@dataclass(frozen=True)
class SeverityHistogram:
    """Counts per band (§1 Vulnerabilities by Severity)."""

    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def ordered(self) -> tuple[tuple[str, int], ...]:
        """(band, count) pairs in canonical severity order (critical→low)."""
        return tuple((band, self.counts.get(band, 0)) for band in SEVERITY_ORDER)

    @property
    def highest_band(self) -> str | None:
        """The most-severe band with a non-zero count, or None when empty."""
        for band in SEVERITY_ORDER:
            if self.counts.get(band, 0) > 0:
                return band
        return None


@dataclass(frozen=True)
class ReportNarrative:
    """The grounded, LLM-written prose. ``faithful`` and the unsupported lists
    record the faithfulness-gate result so the operator sees whether any figure
    could not be grounded in the findings."""

    executive_summary: str
    overall_assessment: str
    faithful: bool = True
    unsupported_numbers: tuple[str, ...] = ()
    unsupported_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssembledReport:
    """The complete structured deliverable — deterministic data + narrative."""

    kind: str
    histogram: SeverityHistogram
    matrix: tuple[MatrixRow, ...]
    technical_findings: tuple[TechnicalFinding, ...]
    narrative: ReportNarrative | None = None
    # Grounding corpus (the plain-text facts the narrative must be grounded in)
    # — carried so a re-run of the faithfulness gate is reproducible.
    grounding_texts: tuple[str, ...] = field(default=())
    # Curation accounting: how many raw board findings were collapsed by dedup,
    # and how many deduped findings are listed in the matrix (§3) but NOT given a
    # full §4 technical section (deferred to keep the report curated, not a dump).
    raw_finding_count: int = 0
    deferred_count: int = 0
    # ── Honesty accounting (never let a report drop findings in silence) ──
    # Findings that matched the report's scope, whether or not they fit.
    total_matched: int = 0
    # Matched but did NOT fit under the scope limit. Non-zero MUST be stated in
    # the document — a truncated report that reads as complete is a lie.
    truncated_count: int = 0
    # In scope but deliberately not listed, per the kind's inclusion policy.
    excluded_resolved: int = 0
    excluded_suppressed: int = 0
    excluded_sample: int = 0
    # Seeded demo findings among the listed ones — non-zero stamps the document.
    sample_finding_count: int = 0
    # Listed findings that never reached the board.
    untriaged_count: int = 0
    # Did anything actually LOOK at this scope? ``None`` = the finding source
    # could not tell. An empty report with no completed scan is an UNSCANNED
    # scope, not a clean one — see ``ScanCoverage`` on the finding port.
    scan_coverage: ScanCoverage | None = None

    @property
    def contains_sample_data(self) -> bool:
        return self.sample_finding_count > 0

    @property
    def has_scan_coverage(self) -> bool:
        """Has a scan actually completed over this scope?

        Fail-closed: unknown coverage is NOT coverage. The document may only make
        a "no findings were surfaced" claim when this is True, because that
        sentence asserts something was reviewed.
        """
        return self.scan_coverage is not None and self.scan_coverage.has_coverage

    @property
    def is_truncated(self) -> bool:
        return self.truncated_count > 0

    @property
    def finding_count(self) -> int:
        return len(self.technical_findings)

    @property
    def distinct_finding_count(self) -> int:
        """Deduped findings — the number of distinct issues (matrix length)."""
        return len(self.matrix)
