"""Deterministic report assembler — the structured core, NO LLM.

Given a workspace, a report kind, and scope filters, this:
  1. pulls the scoped findings (via ``FindingSourcePort`` — the SSOT, with board
     state joined on as enrichment),
  2. sorts them most-severe first and assigns stable FIDs (F-01 … F-NN),
  3. builds each finding's technical section (category, affected asset,
     description, remediation, evidence, triage state) deterministically,
  4. computes the severity histogram and the findings-matrix rows,
  5. carries the **accounting** — what matched, what was truncated, what the
     kind's policy excluded, how much is sample data, how much is untriaged,
  6. builds the grounding corpus (the plain-text facts the narrative writer must
     stay faithful to), including every one of those numbers.

The narrative (exec summary + overall assessment) is NOT written here — the
assembler produces only ground truth. ``GenerateReportUseCase`` calls the
narrative port over this output. Keeping the two apart is what makes the
narrative faithfulness-checkable: the LLM only ever narrates data the assembler
already fixed.

**Nothing is dropped in silence.** Every finding the scope matched is either
listed, or counted in an exclusion the deliverable states. That invariant is the
whole reason this service now consumes a ``FindingPage`` rather than a bare list.

Application layer: orchestrates domain services + the finding port; imports no
Django, no ORM (the port's adapter owns that).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from components.report.application.ports.finding_source_port import (
    FindingQuery,
    FindingSourcePort,
)
from components.report.domain.entities.assembled_report_entity import (
    AssembledReport,
    SeverityHistogram,
)
from components.report.domain.report_kind import get_report_kind
from components.report.domain.services import finding_curation as curation
from components.report.domain.services import finding_section_builder as fsb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssembleScope:
    """The operator-supplied scope for one assembly run."""

    workspace_id: str
    kind: str = "pentest"
    source_types: Sequence[str] | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 500


class ReportAssemblerService:
    def __init__(self, finding_source: FindingSourcePort) -> None:
        self._findings = finding_source

    def assemble(self, scope: AssembleScope) -> AssembledReport:
        spec = get_report_kind(scope.kind)

        page = self._findings.list_findings(
            FindingQuery(
                workspace_id=scope.workspace_id,
                source_prefixes=tuple(spec.finding_source_prefixes),
                sources=tuple(scope.source_types or ()),
                since=scope.since,
                until=scope.until,
                limit=scope.limit,
                include_resolved=spec.include_resolved,
                include_suppressed=spec.include_suppressed,
                include_sample=spec.include_sample,
            )
        )
        raw = page.findings

        # 1. Dedup: collapse near-identical findings (320× "ERROR in celery_worker"
        #    → one issue with occurrences=320). Curation is what turns a 400-page
        #    log dump into a curated deliverable and keeps the narrative prompt sane.
        #    A finding carrying a stable identity (the SSOT's source|fingerprint)
        #    dedups on that key alone and is never fuzzily merged.
        curated = curation.dedupe_findings(raw)

        # 2. Deterministic order over the DISTINCT issues: most-severe first, then
        #    title. FID reflects that and is assigned across ALL deduped findings,
        #    so §3 (matrix, every issue) and §4 (featured subset) share FIDs.
        ordered = sorted(curated, key=lambda c: fsb.sort_key(c.finding))
        all_technicals = tuple(
            fsb.build_technical_finding(item.finding, fid=f"F-{index:02d}", occurrences=item.occurrences)
            for index, item in enumerate(ordered, start=1)
        )

        # 3. The §3 matrix lists every distinct issue; the histogram counts them.
        matrix = tuple(fsb.build_matrix_row(tech) for tech in all_technicals)
        histogram = fsb.build_histogram(all_technicals)

        # 4. Cap the §4 technical write-ups — Critical/High always, then fill to
        #    the kind's max. The rest stay in the matrix (nothing hidden).
        featured = curation.select_featured(
            all_technicals,
            full_detail_bands=spec.full_detail_bands,
            max_count=spec.max_technical_findings,
        )
        deferred_count = len(all_technicals) - len(featured)
        raw_count = sum(item.occurrences for item in curated)
        untriaged_count = sum(1 for tech in all_technicals if not tech.triage.on_board)

        # Grounding is over the FEATURED findings only + the counts — the narrative
        # narrates the report it can see, and the corpus stays within context.
        grounding = build_grounding_texts(
            histogram=histogram,
            featured=featured,
            distinct_count=len(all_technicals),
            raw_count=raw_count,
            deferred_count=deferred_count,
            untriaged_count=untriaged_count,
            truncated_count=page.truncated_count,
            total_matched=page.total_matched,
            excluded_resolved=page.excluded_resolved,
            excluded_suppressed=page.excluded_suppressed,
            excluded_sample=page.excluded_sample,
            sample_count=page.sample_count,
        )

        logger.info(
            "report.assembled workspace_id=%s kind=%s matched=%d returned=%d truncated=%d raw=%d "
            "distinct=%d featured=%d deferred=%d untriaged=%d sample=%d "
            "excluded_resolved=%d excluded_suppressed=%d histogram=%s",
            scope.workspace_id,
            scope.kind,
            page.total_matched,
            page.returned_count,
            page.truncated_count,
            raw_count,
            len(all_technicals),
            len(featured),
            deferred_count,
            untriaged_count,
            page.sample_count,
            page.excluded_resolved,
            page.excluded_suppressed,
            histogram.counts,
        )

        return AssembledReport(
            kind=scope.kind,
            histogram=histogram,
            matrix=matrix,
            technical_findings=featured,
            narrative=None,
            grounding_texts=grounding,
            raw_finding_count=raw_count,
            deferred_count=deferred_count,
            total_matched=page.total_matched,
            truncated_count=page.truncated_count,
            excluded_resolved=page.excluded_resolved,
            excluded_suppressed=page.excluded_suppressed,
            excluded_sample=page.excluded_sample,
            sample_finding_count=page.sample_count,
            untriaged_count=untriaged_count,
        )


def build_grounding_texts(
    *,
    histogram: SeverityHistogram,
    featured: Sequence[Any],
    distinct_count: int,
    raw_count: int,
    deferred_count: int,
    untriaged_count: int = 0,
    truncated_count: int = 0,
    total_matched: int = 0,
    excluded_resolved: int = 0,
    excluded_suppressed: int = 0,
    excluded_sample: int = 0,
    sample_count: int = 0,
) -> tuple[str, ...]:
    """The plain-text corpus the narrative must be grounded in.

    Every fact a faithful narrative can cite — the distinct-issue count, the raw
    observed volume, the per-band counts, what was truncated or excluded, whether
    any of this is sample data, and each featured finding's
    title/category/severity/asset/triage/description — is emitted here so the
    faithfulness verifier can check the LLM's prose against it. Numbers the
    narrative may legitimately state appear as literal digits.

    The accounting lines are in the corpus deliberately: they are the facts that
    let the narrative say "of 1,240 findings, 500 are detailed here" instead of
    confidently implying the report is complete when it is not.

    Only the FEATURED findings' detail is emitted (not the deferred long tail):
    the narrative narrates the report it renders, and the corpus stays within the
    model's context window even when the workspace carried thousands of findings.
    """
    texts: list[str] = [
        f"Distinct findings: {distinct_count}.",
        f"Total findings observed (before de-duplication): {raw_count}.",
    ]
    if sample_count:
        texts.append(
            f"THIS REPORT CONTAINS SAMPLE DATA: {sample_count} of the findings are seeded demonstration "
            f"data, not observations of a real environment. They are marked SAMPLE individually."
        )
    if truncated_count:
        texts.append(
            f"{total_matched} findings matched this report's scope; {distinct_count} are included. "
            f"{truncated_count} findings were not included because the report's scope limit was reached."
        )
    if excluded_resolved:
        texts.append(f"{excluded_resolved} findings were resolved in this period and are not listed as open issues.")
    if excluded_suppressed:
        texts.append(
            f"{excluded_suppressed} findings are suppressed as accepted risk or false positives and are not listed."
        )
    if excluded_sample:
        texts.append(f"{excluded_sample} sample findings were excluded from this report.")
    if untriaged_count:
        texts.append(
            f"{untriaged_count} of the findings listed have not been triaged — they were never picked up "
            f"onto the response board and no owner has been assigned."
        )
    if deferred_count:
        texts.append(
            f"{deferred_count} lower-severity findings are listed in the findings matrix "
            f"without a full technical section."
        )
    for band, count in histogram.ordered():
        texts.append(f"{band.capitalize()} severity findings: {count}.")
    for tech in featured:
        occurrence_note = f" Observed {tech.occurrences} times." if tech.occurrences > 1 else ""
        sample_note = " This is SAMPLE data." if tech.is_sample else ""
        texts.append(
            f"{tech.fid} {tech.title}. Category {tech.category}. "
            f"Severity {tech.severity.label}, indicative CVSS {tech.cvss}. "
            f"Affected asset {tech.affected_asset}. Triage status {tech.triage.label}."
            f"{occurrence_note}{sample_note} {tech.description}"
        )
        for bullet in tech.remediation:
            texts.append(bullet)
    return tuple(texts)
