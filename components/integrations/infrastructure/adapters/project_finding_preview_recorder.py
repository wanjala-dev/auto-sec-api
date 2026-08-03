"""Adapter: record a fix-preview onto its finding via ``project`` (ADR 0012 P6).

Implements :class:`FindingPreviewRecorderPort` by delegating to ``project``'s
application surface (``RecordFindingPreviewUseCase`` via ``ProjectProvider``) — a
permitted cross-context call into another context's application layer, never its
infrastructure/persistence (the same shape as ``ProjectFindingPrRecorder``). The board
``Task`` is ``project``'s data, so ``project`` owns the write; integrations only asks.
"""

from __future__ import annotations

from components.integrations.application.ports.finding_preview_recorder_port import (
    FindingPreviewRecorderPort,
)


class ProjectFindingPreviewRecorder(FindingPreviewRecorderPort):
    def record_preview(
        self,
        *,
        workspace_id: str,
        task_id: str,
        performed_by: str,
        acting_agent: str,
        path: str,
        code: str,
        language: str,
        change_summary: str,
        grounding: tuple[dict, ...],
    ) -> None:
        from components.project.application.ports.record_finding_preview_port import (
            RecordFindingPreviewCommand,
        )
        from components.project.application.providers.project_provider import ProjectProvider

        use_case = ProjectProvider.build_record_finding_preview_use_case()
        use_case.execute(
            command=RecordFindingPreviewCommand(
                workspace_id=str(workspace_id),
                task_id=str(task_id),
                performed_by=str(performed_by),
                acting_agent=acting_agent,
                path=path,
                code=code,
                language=language,
                change_summary=change_summary,
                grounding=tuple(grounding),
            )
        )
