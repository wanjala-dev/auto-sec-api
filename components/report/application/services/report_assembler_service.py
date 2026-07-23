"""Deterministic report assembler — the structured core, NO LLM.

Given a workspace, a report kind, and scope filters, this:
  1. pulls the scoped board findings (via ``FindingSourcePort``),
  2. sorts them most-severe first and assigns stable FIDs (F-01 … F-NN),
  3. builds each finding's technical section (category, affected asset,
     description, remediation, evidence) deterministically,
  4. computes the severity histogram and the findings-matrix rows,
  5. builds the grounding corpus (the plain-text facts the narrative writer must
     stay faithful to).

The narrative (exec summary + overall assessment) is NOT written here — the
assembler produces only ground truth. ``GenerateReportUseCase`` calls the
narrative port over this output. Keeping the two apart is what makes the
narrative faithfulness-checkable: the LLM only ever narrates data the assembler
already fixed.

Application layer: orchestrates domain services + the finding port; imports no
Django, no ORM (the port's adapter owns that).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from components.report.application.ports.finding_source_port import FindingSourcePort
from components.report.domain.entities.assembled_report_entity import AssembledReport
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

        raw = self._findings.list_findings(
            workspace_id=scope.workspace_id,
            source_type_prefixes=spec.source_type_prefixes,
            source_types=scope.source_types,
            since=scope.since,
            until=scope.until,
            limit=scope.limit,
        )

        # 1. Dedup: collapse near-identical findings (320× "ERROR in celery_worker"
        #    → one issue with occurrences=320). Curation is what turns a 400-page
        #    log dump into a curated deliverable and keeps the narrative prompt sane.
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

        # Grounding is over the FEATURED findings only + the counts — the narrative
        # narrates the report it can see, and the corpus stays within context.
        grounding = build_grounding_texts(
            histogram=histogram,
            featured=featured,
            distinct_count=len(all_technicals),
            raw_count=raw_count,
            deferred_count=deferred_count,
        )

        logger.info(
            "report.assembled workspace_id=%s kind=%s raw=%d distinct=%d featured=%d deferred=%d histogram=%s",
            scope.workspace_id,
            scope.kind,
            raw_count,
            len(all_technicals),
            len(featured),
            deferred_count,
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
        )


def build_grounding_texts(
    *,
    histogram: SeverityHistogram,
    featured: Sequence[Any],
    distinct_count: int,
    raw_count: int,
    deferred_count: int,
) -> tuple[str, ...]:
    """The plain-text corpus the narrative must be grounded in.

    Every fact a faithful narrative can cite — the distinct-issue count, the raw
    observed volume, the per-band counts, and each featured finding's
    title/category/severity/asset/description — is emitted here so the
    faithfulness verifier can check the LLM's prose against it. Numbers the
    narrative may legitimately state appear as literal digits.

    Only the FEATURED findings' detail is emitted (not the deferred long tail):
    the narrative narrates the report it renders, and the corpus stays within the
    model's context window even when the board carried hundreds of raw findings.
    """
    texts: list[str] = [
        f"Distinct findings: {distinct_count}.",
        f"Total findings observed (before de-duplication): {raw_count}.",
    ]
    if deferred_count:
        texts.append(
            f"{deferred_count} lower-severity findings are listed in the findings matrix "
            f"without a full technical section."
        )
    for band, count in histogram.ordered():
        texts.append(f"{band.capitalize()} severity findings: {count}.")
    for tech in featured:
        occurrence_note = f" Observed {tech.occurrences} times." if tech.occurrences > 1 else ""
        texts.append(
            f"{tech.fid} {tech.title}. Category {tech.category}. "
            f"Severity {tech.severity.label}, indicative CVSS {tech.cvss}. "
            f"Affected asset {tech.affected_asset}.{occurrence_note} {tech.description}"
        )
        for bullet in tech.remediation:
            texts.append(bullet)
    return tuple(texts)
