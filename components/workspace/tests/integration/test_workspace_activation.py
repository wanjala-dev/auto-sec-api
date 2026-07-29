"""A freshly-created workspace is activated so me/summary + the HUD surface it
(the model defaults status to 'inactive'; nothing else flips it)."""

from __future__ import annotations

import pytest

from components.workspace.infrastructure.repositories.workspace_bootstrap_repository import (
    WorkspaceBootstrapRepository,
)
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = [pytest.mark.django_db]


class TestWorkspaceActivation:
    def test_activate_flips_inactive_to_active(self, workspace_factory):
        workspace = workspace_factory(status="inactive")
        assert workspace.status == "inactive"

        WorkspaceBootstrapRepository().activate_workspace(workspace=workspace)

        # persisted + now visible through the default (active-only) manager.
        assert Workspace.objects.filter(id=workspace.id).exists()
        assert Workspace.objects.get(id=workspace.id).status == "active"

    def test_activate_is_idempotent_on_already_active(self, workspace_factory):
        workspace = workspace_factory(status="active")
        WorkspaceBootstrapRepository().activate_workspace(workspace=workspace)
        assert Workspace.objects.get(id=workspace.id).status == "active"
