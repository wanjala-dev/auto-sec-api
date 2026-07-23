"""Narrate grounded report prose over caller-supplied findings.

The cross-context entry point the ``report_agent`` calls: it takes a list of
finding dicts (title/severity/category/affected_asset), shapes them through the
SAME deterministic section builder + grounding corpus the assembler uses, and
runs the grounded narrative writer over them — WITHOUT persisting or generating
anything. This keeps the agent (another context's infrastructure) out of the
report domain entities: it calls this application use case and gets back a plain
dict.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from components.report.application.ports.report_narrative_port import ReportNarrativePort
from components.report.application.services.report_assembler_service import build_grounding_texts
from components.report.domain.entities.assembled_report_entity import AssembledReport
from components.report.domain.services import finding_section_builder as fsb

logger = logging.getLogger(__name__)


class NarrateSuppliedFindingsUseCase:
    def __init__(self, *, narrative: ReportNarrativePort) -> None:
        self._narrative = narrative

    def execute(
        self,
        *,
        findings: Sequence[Mapping[str, Any]],
        workspace_name: str,
        engagement_title: str = "",
        scope_summary: str = "",
    ) -> dict[str, Any]:
        shaped = [self._shape(f) for f in findings if isinstance(f, Mapping)]
        shaped = [f for f in shaped if f is not None]
        if not shaped:
            return {"error": "no_valid_findings"}

        ordered = sorted(shaped, key=fsb.sort_key)
        technicals = tuple(fsb.build_technical_finding(f, fid=f"F-{i:02d}") for i, f in enumerate(ordered, start=1))
        assembled = AssembledReport(
            kind="pentest",
            histogram=fsb.build_histogram(technicals),
            matrix=tuple(fsb.build_matrix_row(t) for t in technicals),
            technical_findings=technicals,
            grounding_texts=build_grounding_texts(ordered, technicals),
        )
        narrative = self._narrative.write(
            assembled=assembled,
            workspace_name=workspace_name,
            engagement_title=engagement_title,
            scope_summary=scope_summary,
        )
        return {
            "executive_summary": narrative.executive_summary,
            "overall_assessment": narrative.overall_assessment,
            "faithful": narrative.faithful,
            "unsupported_figures": list(narrative.unsupported_numbers),
        }

    @staticmethod
    def _shape(f: Mapping[str, Any]) -> dict[str, Any] | None:
        title = str(f.get("title") or "").strip()
        if not title:
            return None
        return {
            "id": str(f.get("id") or ""),
            "title": title,
            "description": str(f.get("description") or ""),
            "source_type": "ai.supplied",
            "status": "todo",
            "created_at": None,
            "metadata": {
                "severity": str(f.get("severity") or "low"),
                "action_type": str(f.get("category") or ""),
                "ai_headline": title,
                "ai_narrative": str(f.get("description") or ""),
                "payload": {
                    "service": str(f.get("affected_asset") or ""),
                    "signal": str(f.get("description") or ""),
                },
            },
        }
