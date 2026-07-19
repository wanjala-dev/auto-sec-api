from __future__ import annotations

from components.workspace.domain.policies.workspace_setup_policy_service import (
    WorkspaceSetupPolicyService,
    WorkspaceSetupSnapshot,
)


def test_workspace_setup_policy_builds_pending_status_payload():
    service = WorkspaceSetupPolicyService()
    snapshot = WorkspaceSetupSnapshot(
        workspace_id="workspace-1",
        workspace_name="Alpha",
        has_contribution_means=True,
        has_story=False,
        has_cover_photo=False,
        has_budget=True,
        has_active_team=False,
    )

    status = service.build_status(snapshot)

    assert status["workspace"] == "workspace-1"
    assert status["workspace_name"] == "Alpha"
    assert status["is_complete"] is False
    assert status["pending"] == ["has_story", "has_cover_photo", "has_active_team"]
    assert [item["code"] for item in status["recommendations"]] == status["pending"]


def test_workspace_setup_policy_reports_complete_workspace():
    service = WorkspaceSetupPolicyService()
    snapshot = WorkspaceSetupSnapshot(
        workspace_id="workspace-1",
        workspace_name="Alpha",
        has_contribution_means=True,
        has_story=True,
        has_cover_photo=True,
        has_budget=True,
        has_active_team=True,
    )

    results = service.evaluate(snapshot)

    assert all(result.is_complete for result in results)
