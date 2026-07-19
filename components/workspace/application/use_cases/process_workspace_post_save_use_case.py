from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.team.application.use_cases.sync_workspace_ai_teammate_use_case import (
    SyncWorkspaceAiTeammateUseCase,
)
from components.workspace.application.ports.workspace_post_save_port import WorkspacePostSavePort


@dataclass
class ProcessWorkspacePostSaveUseCase:
    workspace_post_save_port: WorkspacePostSavePort
    ai_teammate_use_case: SyncWorkspaceAiTeammateUseCase

    def execute(self, *, workspace: Any, created: bool) -> None:
        self.workspace_post_save_port.enqueue_embeddings(workspace=workspace)
        if created:
            self.workspace_post_save_port.bootstrap_defaults(workspace=workspace)
        self.ai_teammate_use_case.execute(workspace=workspace)
