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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from components.report.application.ports.finding_source_port import FindingSourcePort
from components.report.domain.entities.assembled_report_entity import AssembledReport
from components.report.domain.report_kind import get_report_kind
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

        # Deterministic order: most-severe first, then title. FID reflects that.
        ordered = sorted(raw, key=fsb.sort_key)
        technicals = tuple(
            fsb.build_technical_finding(finding, fid=f"F-{index:02d}") for index, finding in enumerate(ordered, start=1)
        )
        matrix = tuple(fsb.build_matrix_row(tech) for tech in technicals)
        histogram = fsb.build_histogram(technicals)
        grounding = build_grounding_texts(ordered, technicals)

        logger.info(
            "report.assembled workspace_id=%s kind=%s findings=%d histogram=%s",
            scope.workspace_id,
            scope.kind,
            len(technicals),
            histogram.counts,
        )

        return AssembledReport(
            kind=scope.kind,
            histogram=histogram,
            matrix=matrix,
            technical_findings=technicals,
            narrative=None,
            grounding_texts=grounding,
        )


def build_grounding_texts(
    ordered: Sequence[Mapping[str, Any]],
    technicals: Sequence[Any],
) -> tuple[str, ...]:
    """The plain-text corpus the narrative must be grounded in.

    Every fact a faithful narrative can cite — the finding count, the per-band
    counts, and each finding's title/category/severity/asset/description — is
    emitted here so the faithfulness verifier can check the LLM's prose against
    it. Numbers the narrative may legitimately state (counts, CVSS) appear as
    literal digits in the corpus.
    """
    from components.report.domain.services.finding_section_builder import build_histogram

    histogram = build_histogram(technicals)
    texts: list[str] = [
        f"Total findings: {histogram.total}.",
    ]
    for band, count in histogram.ordered():
        texts.append(f"{band.capitalize()} severity findings: {count}.")
    for tech in technicals:
        texts.append(
            f"{tech.fid} {tech.title}. Category {tech.category}. "
            f"Severity {tech.severity.label}, indicative CVSS {tech.cvss}. "
            f"Affected asset {tech.affected_asset}. {tech.description}"
        )
        for bullet in tech.remediation:
            texts.append(bullet)
    return tuple(texts)
