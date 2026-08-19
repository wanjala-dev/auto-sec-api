"""Report-kind registry — the seam that keeps this context kind-extensible.

Pentest is the first (and today only) kind; compliance / posture / exec-brief
plug in by adding one ``ReportKindSpec`` to ``REPORT_KINDS`` — no assembler,
controller, or model change. Mirrors the Template Kernel's kind-registry
*pattern* (``components/templates/domain/template_kind.py``) without coupling to
it: a report kind is data-only and this module imports nothing framework.

Each kind declares:
  - ``id`` / ``title`` — the id persisted on ``Report.kind`` and the document's
    display title ("Penetration Test Report").
  - ``template_name`` — the Django template the HTML builder renders.
  - ``section_order`` — the numbered sections, in order, for the ToC.
  - ``finding_source_prefixes`` — which SSOT findings this kind pulls (a finding
    is in scope when its ``Finding.source`` starts with any of these). EMPTY =
    every source in the workspace, which is the pentest default: a report about
    "your security posture" must not silently omit a pillar.
  - ``source_type_prefixes`` — the same scope expressed in BOARD vocabulary, for
    the board-only ``BoardFindingRepository`` lens (``Task.source_type``).
  - ``include_resolved`` / ``include_suppressed`` / ``include_sample`` — the
    kind's inclusion policy. Whatever a kind excludes is still COUNTED and
    stated in the deliverable; nothing is ever dropped in silence.
  - ``narrative_sections`` — the sections the grounded narrative writer fills
    (everything else the assembler fills deterministically).

Pure domain: no Django, no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class UnknownReportKind(ValueError):
    """Raised when a caller asks for a kind that is not registered."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"Unknown report kind: {kind!r}. Registered: {', '.join(sorted(REPORT_KINDS))}")
        self.kind = kind


@dataclass(frozen=True)
class ReportKindSpec:
    """Immutable declaration of one report kind."""

    id: str
    title: str
    template_name: str
    section_order: tuple[str, ...]
    source_type_prefixes: tuple[str, ...]
    finding_source_prefixes: tuple[str, ...] = field(default=())
    narrative_sections: tuple[str, ...] = field(default=("executive_summary", "overall_assessment"))
    # ── Inclusion policy (see the module docstring) ──
    # A RESOLVED finding is "what we closed this period", not a live
    # vulnerability: listing it in the Findings Matrix would overstate the
    # assessment. A SUPPRESSED finding is an accepted risk / false positive the
    # operator explicitly dismissed: listing it as identified would misrepresent
    # a decision that was made. Both are excluded from the matrix and their
    # counts are stated in the document, which is what an auditor actually wants.
    include_resolved: bool = False
    include_suppressed: bool = False
    # Seeded demo findings ARE included — an empty demo report is its own kind of
    # dishonesty — and the document is stamped as containing sample data, with a
    # per-finding marker. See ``report_context_mapper``.
    include_sample: bool = True
    # Curation policy (see components/report/domain/services/finding_curation.py):
    #  - full_detail_bands: severity bands that ALWAYS get a full §4 technical
    #    write-up, however many there are — a report must never bury a high.
    #  - max_technical_findings: cap on §4 sections; lower-severity findings fill
    #    the remaining slots, and the rest are listed in the §3 matrix only.
    # This is what makes a report read like a curated deliverable rather than a
    # verbatim dump of every board card.
    full_detail_bands: tuple[str, ...] = field(default=("critical", "high"))
    max_technical_findings: int = 25
    # Default document confidentiality footer — the deliverable is client-
    # privileged. Concrete client/vendor names are interpolated by the builder.
    confidentiality: str = (
        "This document is confidential and privileged. It is intended only for "
        "the named recipient and may not be used, published, or redistributed "
        "without prior written consent."
    )


# ── The registry ───────────────────────────────────────────────────────────
PENTEST = "pentest"

REPORT_KINDS: dict[str, ReportKindSpec] = {
    PENTEST: ReportKindSpec(
        id=PENTEST,
        title="Penetration Test Report",
        template_name="report/pentest_report.html",
        section_order=(
            "Executive Summary",
            "Engagement Scope and Approach",
            "Findings Matrix",
            "Technical Findings",
            "Appendix A — Methodology",
            "Appendix B — Severity Ratings",
        ),
        # Every finding in the workspace is a pentest-report candidate — the
        # SSOT is the spine, so nothing is filtered out by which pillar produced
        # it or whether it happened to reach the board. The operator narrows by
        # scope filters at generation time.
        finding_source_prefixes=(),
        # Board-lens equivalent, used only by ``BoardFindingRepository``.
        source_type_prefixes=("ai.",),
        narrative_sections=("executive_summary", "overall_assessment"),
    ),
    # Seam for future kinds — add here, nothing else changes:
    # COMPLIANCE = "compliance"; POSTURE = "posture"; EXEC_BRIEF = "exec_brief".
}


def get_report_kind(kind: str) -> ReportKindSpec:
    """Return the spec for ``kind`` or raise :class:`UnknownReportKind`."""
    spec = REPORT_KINDS.get(kind)
    if spec is None:
        raise UnknownReportKind(kind)
    return spec


def registered_kinds() -> tuple[ReportKindSpec, ...]:
    """All registered kinds, id-sorted — used to render the kind picker."""
    return tuple(REPORT_KINDS[k] for k in sorted(REPORT_KINDS))
