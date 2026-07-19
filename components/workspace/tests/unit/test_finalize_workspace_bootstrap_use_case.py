from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.workspace.application.use_cases.finalize_workspace_bootstrap_use_case import (
    FinalizeWorkspaceBootstrapUseCase,
)


def test_finalize_workspace_bootstrap_use_case_updates_owner_profile_and_theme():
    workspace_bootstrap_store = Mock()
    owner = object()
    workspace = SimpleNamespace(id="workspace-1")
    use_case = FinalizeWorkspaceBootstrapUseCase(
        workspace_bootstrap_store=workspace_bootstrap_store,
    )

    use_case.execute(
        owner=owner,
        workspace=workspace,
        active_team_id="team-1",
        theme_spec={"primary": "#123456"},
    )

    workspace_bootstrap_store.finalize_owner_profile.assert_called_once_with(
        owner=owner,
        workspace_id="workspace-1",
        active_team_id="team-1",
    )
    workspace_bootstrap_store.ensure_theme.assert_called_once_with(
        workspace=workspace,
        theme_spec={"primary": "#123456"},
    )
