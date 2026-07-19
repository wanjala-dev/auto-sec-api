from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.workspace.application.ports.workspace_bootstrap_port import WorkspaceBootstrapPort


@dataclass
class FinalizeWorkspaceBootstrapUseCase:
    workspace_bootstrap_store: WorkspaceBootstrapPort

    def execute(
        self,
        *,
        owner: Any,
        workspace: Any,
        active_team_id: Any,
        theme_spec: dict[str, Any] | None = None,
    ) -> None:
        self.workspace_bootstrap_store.finalize_owner_profile(
            owner=owner,
            workspace_id=workspace.id,
            active_team_id=active_team_id,
        )
        self.workspace_bootstrap_store.ensure_theme(
            workspace=workspace,
            theme_spec=theme_spec,
        )
