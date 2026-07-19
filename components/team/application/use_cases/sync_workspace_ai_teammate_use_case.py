from __future__ import annotations

from components.team.application.ports.workspace_ai_teammate_sync_port import (
    WorkspaceAiTeammateSyncPort,
)


class SyncWorkspaceAiTeammateUseCase:
    def __init__(
        self,
        *,
        workspace_ai_teammate_sync_port: WorkspaceAiTeammateSyncPort,
    ) -> None:
        self.workspace_ai_teammate_sync_port = workspace_ai_teammate_sync_port

    def execute(self, *, workspace) -> None:
        self.workspace_ai_teammate_sync_port.sync(workspace=workspace)
