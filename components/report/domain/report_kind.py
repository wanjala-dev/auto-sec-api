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
  - ``source_type_prefixes`` — which board findings this kind pulls. A finding is
    in scope when its ``Task.source_type`` starts with any of these (all
    ``ai.*`` today, so every AI finding is a candidate; a future compliance kind
    could pull a narrower slice).
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
    narrative_sections: tuple[str, ...] = field(default=("executive_summary", "overall_assessment"))
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
        # Every AI finding on the board is a pentest-report candidate; the
        # operator narrows by scope filters at generation time.
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
