"""Integration tests — WorkspaceQueryPort.get_ai_toggle_status (kill-switch read).

The AI-governance kill-switch report reads the workspace's ``ai_teammate_enabled``
toggle through this port. The behaviour that MUST be preserved from the prior inline
``Workspace._base_manager`` read: an inactive/soft-deleted workspace is still
*found* (so the report reflects a halted workspace, not treats it as absent), and a
missing row yields ``found=False``.
"""

from __future__ import annotations

import pytest

from components.agents.application.ports.cross_context_query_port import WorkspaceAiToggleStatus
from components.agents.infrastructure.repositories.orm_cross_context_repository import (
    OrmWorkspaceQueryAdapter,
)


@pytest.fixture()
def adapter():
    return OrmWorkspaceQueryAdapter()


@pytest.mark.django_db
class TestWorkspaceAiToggleStatus:
    def test_active_workspace_found_with_toggle(self, adapter, workspace_factory):
        ws = workspace_factory()
        ws.ai_teammate_enabled = True
        ws.save(update_fields=["ai_teammate_enabled"])

        status = adapter.get_ai_toggle_status(str(ws.id))

        assert status == WorkspaceAiToggleStatus(found=True, ai_teammate_enabled=True)

    def test_inactive_workspace_still_found(self, adapter, workspace_factory):
        # The base-manager read must see a workspace even when it is inactive —
        # the default WorkspaceManager filters status="active" out, so this proves
        # the kill-switch report still reflects a halted/inactive workspace.
        ws = workspace_factory()
        ws.ai_teammate_enabled = False
        ws.status = "inactive"
        ws.save(update_fields=["ai_teammate_enabled", "status"])

        status = adapter.get_ai_toggle_status(str(ws.id))

        assert status.found is True
        assert status.ai_teammate_enabled is False

    def test_missing_workspace_reports_not_found(self, adapter):
        status = adapter.get_ai_toggle_status("00000000-0000-0000-0000-000000000000")

        assert status == WorkspaceAiToggleStatus(found=False, ai_teammate_enabled=False)
