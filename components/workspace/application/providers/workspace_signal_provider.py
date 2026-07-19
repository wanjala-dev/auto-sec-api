from __future__ import annotations

from components.team.application.use_cases.sync_workspace_ai_teammate_use_case import (
    SyncWorkspaceAiTeammateUseCase,
)
from components.team.infrastructure.adapters.workspace_ai_teammate_sync_adapter import (
    WorkspaceAiTeammateSyncAdapter,
)
from components.workspace.application.use_cases.process_workspace_post_save_use_case import (
    ProcessWorkspacePostSaveUseCase,
)
from components.workspace.infrastructure.adapters.django_workspace_signal_bridge import (
    DjangoWorkspaceSignalBridge,
)
from components.workspace.infrastructure.adapters.workspace_post_save_adapter import (
    WorkspacePostSaveAdapter,
)


class WorkspaceSignalProvider:
    def register_signal_handlers(self) -> None:
        DjangoWorkspaceSignalBridge().register(
            handler=self.build_post_save_use_case(),
        )

    def build_post_save_use_case(self) -> ProcessWorkspacePostSaveUseCase:
        return ProcessWorkspacePostSaveUseCase(
            workspace_post_save_port=WorkspacePostSaveAdapter(),
            ai_teammate_use_case=self.build_sync_ai_teammate_use_case(),
        )

    def build_sync_ai_teammate_use_case(self) -> SyncWorkspaceAiTeammateUseCase:
        return SyncWorkspaceAiTeammateUseCase(
            workspace_ai_teammate_sync_port=WorkspaceAiTeammateSyncAdapter(),
        )
