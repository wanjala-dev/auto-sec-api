"""Adapter: record an opened draft PR onto its finding via ``project``.

Implements :class:`FindingPrRecorderPort` by delegating to ``project``'s
application surface (``RecordFindingDraftPrUseCase`` via ``ProjectProvider``) — a
permitted cross-context call into another context's application layer, never its
infrastructure/persistence (the same shape as remediation's ``SignOffGateAdapter``
delegating to ``sign_off``'s application service). The board ``Task`` is
``project``'s data, so ``project`` owns the write; integrations only asks for it.
"""

from __future__ import annotations

from components.integrations.application.ports.finding_pr_recorder_port import FindingPrRecorderPort


class ProjectFindingPrRecorder(FindingPrRecorderPort):
    def record_draft_pr(
        self,
        *,
        workspace_id: str,
        task_id: str,
        performed_by: str,
        acting_agent: str,
        pr_url: str,
        pr_repo: str,
        branch: str,
        verification: str = "",
        verification_gap: str = "",
    ) -> None:
        from components.project.application.ports.record_finding_draft_pr_port import (
            RecordFindingDraftPrCommand,
        )
        from components.project.application.providers.project_provider import ProjectProvider

        use_case = ProjectProvider.build_record_finding_draft_pr_use_case()
        use_case.execute(
            command=RecordFindingDraftPrCommand(
                workspace_id=str(workspace_id),
                task_id=str(task_id),
                performed_by=str(performed_by),
                acting_agent=acting_agent,
                pr_url=pr_url,
                pr_repo=pr_repo,
                branch=branch,
                verification=verification,
                verification_gap=verification_gap,
            )
        )
