"""The workflows-index read surface: workspace-wide run listing + last-run summary.

The WORKFLOWS header tab landed operators on a blank builder canvas; the index
in front of it needs two reads this suite locks down:

1. ``GET /workspaces/workflows/workflow-runs/?workspace=<id>`` — recent runs
   across every workflow in the workspace (was a hard 405). A workspace
   identifier is REQUIRED (400 without one) and membership is enforced (403
   for a non-member), so there is still no unscoped or cross-tenant listing.
2. The workflow list summary now carries ``last_run_at`` / ``last_run_status``
   (repository annotations), so the index shows "last run + how it went" per
   row without an N+1.
"""

from __future__ import annotations

import pytest

from components.workflow.application.service import WorkflowService
from components.workflow.mappers.rest.workflow_serializers import (
    WorkflowSummarySerializer,
)
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
)

pytestmark = pytest.mark.django_db

_BASE = "/workspaces/workflows"


def _workflow(workspace, name="Flow"):
    return Workflow.objects.create(
        workspace=workspace,
        name=name,
        goal="security",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph={"nodes": [], "edges": []},
    )


def _run(workflow, status=WorkflowRun.Status.COMPLETED):
    return WorkflowRun.objects.create(
        workflow=workflow,
        status=status,
        trigger_type="manual",
        target_type="workspace",
        target_id=str(workflow.workspace_id),
    )


class TestWorkspaceRunList:
    def test_lists_runs_across_the_workspace_newest_first(self, api_client, user_factory, workspace_factory):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        wf_a = _workflow(workspace, name="Alpha")
        wf_b = _workflow(workspace, name="Beta")
        _run(wf_a, WorkflowRun.Status.COMPLETED)
        newest = _run(wf_b, WorkflowRun.Status.FAILED)

        api_client.force_authenticate(user=user)
        response = api_client.get(f"{_BASE}/workflow-runs/", {"workspace": str(workspace.id)})

        assert response.status_code == 200
        results = response.data["results"]
        assert len(results) == 2
        assert results[0]["id"] == str(newest.id)
        assert results[0]["workflow_name"] == "Beta"
        assert results[0]["status"] == "failed"

    def test_workspace_identifier_is_required(self, api_client, user_factory, workspace_factory):
        user = user_factory()
        workspace_factory(owner=user)
        api_client.force_authenticate(user=user)

        response = api_client.get(f"{_BASE}/workflow-runs/")

        # The permission layer rejects the missing workspace before the view
        # (IsOrgOwnerOrMember requires an org identifier for list actions);
        # the view's own guard returns 400. Either way: no unscoped listing.
        assert response.status_code in (400, 403)

    def test_non_member_cannot_list_another_workspaces_runs(self, api_client, user_factory, workspace_factory):
        owner = user_factory()
        outsider = user_factory()
        workspace = workspace_factory(owner=owner)
        _run(_workflow(workspace))

        api_client.force_authenticate(user=outsider)
        response = api_client.get(f"{_BASE}/workflow-runs/", {"workspace": str(workspace.id)})

        assert response.status_code == 403

    def test_scopes_to_the_requested_workspace(self, api_client, user_factory, workspace_factory):
        user = user_factory()
        mine = workspace_factory(owner=user)
        other = workspace_factory(owner=user)
        visible = _run(_workflow(mine, name="Mine"))
        _run(_workflow(other, name="Other"))

        api_client.force_authenticate(user=user)
        response = api_client.get(f"{_BASE}/workflow-runs/", {"workspace": str(mine.id)})

        assert response.status_code == 200
        ids = [row["id"] for row in response.data["results"]]
        assert ids == [str(visible.id)]


class TestLastRunSummary:
    def test_summary_carries_last_run_at_and_status(self, workspace_factory):
        workspace = workspace_factory()
        wf = _workflow(workspace)
        _run(wf, WorkflowRun.Status.COMPLETED)
        latest = _run(wf, WorkflowRun.Status.FAILED)

        row = WorkflowService().get_workflows(workspace_id=str(workspace.id)).get(pk=wf.pk)
        data = WorkflowSummarySerializer(row).data

        assert data["last_run_status"] == "failed"
        assert data["last_run_at"] is not None
        assert row.last_run_at == latest.created_at

    def test_summary_is_null_for_never_run_workflows(self, workspace_factory):
        workspace = workspace_factory()
        wf = _workflow(workspace)

        row = WorkflowService().get_workflows(workspace_id=str(workspace.id)).get(pk=wf.pk)
        data = WorkflowSummarySerializer(row).data

        assert data["last_run_at"] is None
        assert data["last_run_status"] is None
