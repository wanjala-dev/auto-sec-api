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
        has_cloud_connected=True,
        has_first_scan=False,
        has_findings_triaged=False,
        has_teammates_invited=True,
        has_slack_connected=False,
    )

    status = service.build_status(snapshot)

    assert status["workspace"] == "workspace-1"
    assert status["workspace_name"] == "Alpha"
    assert status["is_complete"] is False
    # Pending codes, ordered by the funnel priority (scan → triage → slack).
    assert status["pending"] == ["first_scan", "findings_triaged", "slack_connected"]
    assert [item["code"] for item in status["recommendations"]] == status["pending"]


def test_workspace_setup_policy_reports_complete_workspace():
    service = WorkspaceSetupPolicyService()
    snapshot = WorkspaceSetupSnapshot(
        workspace_id="workspace-1",
        workspace_name="Alpha",
        has_cloud_connected=True,
        has_first_scan=True,
        has_findings_triaged=True,
        has_teammates_invited=True,
        has_slack_connected=True,
    )

    results = service.evaluate(snapshot)

    assert all(result.is_complete for result in results)
