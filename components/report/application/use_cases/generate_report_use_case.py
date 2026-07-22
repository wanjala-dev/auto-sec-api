"""Generate one report end to end.

Orchestrates the whole pipeline for an already-created ``Report`` row:
  1. assemble the scoped findings (deterministic ground truth),
  2. narrate the exec-summary + overall-assessment over that ground truth
     (grounded, faithfulness-gated),
  3. render the branded HTML (workspace org identity on the cover),
  4. render the PDF and store it in object storage,
  5. persist the assembled data + pdf key and flip the row to ``generated``.

Any failure flips the row to ``failed`` with the error so the operator sees it —
we never leave a report stuck ``generating``.

Application layer: orchestrates ports; the HTML builder is reached as an
infrastructure adapter (Django template rendering) — the one framework touch is
isolated to that call, mirroring how reports render their PDFs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from components.report.application.ports.finding_source_port import FindingSourcePort
from components.report.application.ports.report_narrative_port import ReportNarrativePort
from components.report.application.ports.report_pdf_renderer_port import ReportPdfRendererPort
from components.report.application.ports.report_repository_port import ReportRepositoryPort
from components.report.application.ports.workspace_identity_port import WorkspaceIdentityPort
from components.report.application.services.report_assembler_service import (
    AssembleScope,
    ReportAssemblerService,
)
from components.report.domain.entities.assembled_report import AssembledReport
from components.report.mappers.db.assembled_report_mapper import assembled_to_dict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateReportCommand:
    report_id: str
    workspace_id: str


class GenerateReportUseCase:
    def __init__(
        self,
        *,
        reports: ReportRepositoryPort,
        finding_source: FindingSourcePort,
        narrative: ReportNarrativePort,
        renderer: ReportPdfRendererPort,
        storage,
        workspace_identity: WorkspaceIdentityPort,
        html_builder=None,
    ) -> None:
        self._reports = reports
        self._assembler = ReportAssemblerService(finding_source)
        self._narrative = narrative
        self._renderer = renderer
        self._storage = storage
        self._identity = workspace_identity
        self._html_builder = html_builder  # injected for tests; resolved lazily

    def execute(self, command: GenerateReportCommand) -> None:
        report = self._reports.get(report_id=command.report_id, workspace_id=command.workspace_id)
        if report is None:
            logger.warning("report.generate_missing report_id=%s", command.report_id)
            return

        self._reports.mark_generating(report_id=command.report_id)
        try:
            assembled = self._assemble_and_narrate(report)
            html = self._render_html(report, assembled)
            pdf_bytes = self._renderer.render(
                html=html,
                log_context={"report_id": command.report_id, "workspace_id": command.workspace_id},
            )
            key = self._storage.object_key(workspace_id=command.workspace_id, report_id=command.report_id)
            self._storage.put_pdf(key=key, body=pdf_bytes)
            self._reports.mark_generated(
                report_id=command.report_id,
                assembled=assembled_to_dict(assembled),
                finding_count=assembled.finding_count,
                pdf_key=key,
            )
            logger.info(
                "report.generated report_id=%s findings=%d faithful=%s",
                command.report_id,
                assembled.finding_count,
                assembled.narrative.faithful if assembled.narrative else True,
            )
        except Exception as exc:
            logger.exception("report.generate_failed report_id=%s", command.report_id)
            self._reports.mark_failed(report_id=command.report_id, error_message=str(exc))
            raise

    # ── steps ───────────────────────────────────────────────────────────

    def _assemble_and_narrate(self, report: dict[str, Any]) -> AssembledReport:
        scope = report.get("scope") or {}
        assembled = self._assembler.assemble(
            AssembleScope(
                workspace_id=report["workspace_id"],
                kind=report["kind"],
                source_types=scope.get("source_types") or None,
                since=_parse_dt(scope.get("since")),
                until=_parse_dt(scope.get("until")),
                limit=int(scope.get("limit") or 500),
            )
        )
        identity = self._identity.get(workspace_id=report["workspace_id"])
        narrative = self._narrative.write(
            assembled=assembled,
            workspace_name=identity.name,
            engagement_title=report.get("title") or "",
            scope_summary=scope.get("scope_summary") or "",
        )
        # Re-bind the narrative onto the assembled entity (frozen → rebuild).
        return AssembledReport(
            kind=assembled.kind,
            histogram=assembled.histogram,
            matrix=assembled.matrix,
            technical_findings=assembled.technical_findings,
            narrative=narrative,
            grounding_texts=assembled.grounding_texts,
        )

    def _render_html(self, report: dict[str, Any], assembled: AssembledReport) -> str:
        builder = self._html_builder
        if builder is None:
            from components.report.infrastructure.adapters.report_html_builder import build_report_html

            builder = build_report_html
        identity = self._identity.get(workspace_id=report["workspace_id"])
        return builder(
            assembled=assembled,
            kind=report["kind"],
            title=report.get("title") or "",
            scope=report.get("scope") or {},
            workspace_id=report["workspace_id"],
            workspace_name=identity.name,
            workspace_logo_url=identity.logo_url,
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
