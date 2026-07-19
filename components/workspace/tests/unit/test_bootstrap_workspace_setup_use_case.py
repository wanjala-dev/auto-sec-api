from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.workspace.application.use_cases.bootstrap_workspace_setup_use_case import (
    BootstrapWorkspaceSetupUseCase,
)


def test_workspace_setup_use_case_bootstraps_owner_workspace_and_scaffolding():
    workspace_bootstrap_store = Mock()
    owner = SimpleNamespace(email="owner@example.com")
    workspace = SimpleNamespace(id="workspace-1", workspace_name="Alpha", sector_id="personal")
    contributors_team = SimpleNamespace(id="team-1")
    staff_team = SimpleNamespace(id="team-2")
    budget = object()
    workspace_bootstrap_store.ensure_owner.return_value = owner
    workspace_bootstrap_store.ensure_workspace.return_value = (workspace, True)
    workspace_bootstrap_store.ensure_workspace_scaffolding.return_value = (
        contributors_team,
        budget,
    )
    workspace_bootstrap_store.ensure_staff_team.return_value = staff_team
    use_case = BootstrapWorkspaceSetupUseCase(
        workspace_bootstrap_store=workspace_bootstrap_store,
    )

    result = use_case.execute(
        {
            "owner": {"email": owner.email},
            "workspace": {"name": "Alpha"},
        },
        owner_email_override="override@example.com",
        owner_password_override="secret",
    )

    workspace_bootstrap_store.ensure_owner.assert_called_once()
    workspace_bootstrap_store.ensure_workspace.assert_called_once()
    workspace_bootstrap_store.assign_categories.assert_called_once()
    workspace_bootstrap_store.assign_contribution_means.assert_called_once()
    workspace_bootstrap_store.ensure_subscription_plans.assert_called_once()
    workspace_bootstrap_store.ensure_workspace_scaffolding.assert_called_once_with(
        workspace=workspace,
        owner=owner,
        team_title="Family",
    )
    workspace_bootstrap_store.ensure_staff_team.assert_called_once_with(
        workspace=workspace,
        owner=owner,
        title="Staff Team",
    )
    assert result.owner is owner
    assert result.workspace is workspace
    assert result.contributors_team is contributors_team
    assert result.staff_team is staff_team
    assert result.budget is budget
    assert result.created is True
