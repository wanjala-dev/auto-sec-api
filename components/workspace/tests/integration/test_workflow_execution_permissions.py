"""Tests for workflow execution permissions and error envelopes."""

import pytest

from infrastructure.persistence.workspaces.workflows.models import Workflow


@pytest.mark.django_db
class TestWorkflowExecutionAuth:
    """Exercise workflow execution auth paths and error formatting."""

    def test_authenticated_run_creation(self, api_client, workspace_factory, monkeypatch):
        workspace = workspace_factory()
        workflow = Workflow.objects.create(
            workspace=workspace,
            name="Service run",
            goal="sponsorship",
            graph={"nodes": [{"id": "start", "type": "start", "title": "Start"}], "edges": []},
        )

        # Run dispatch moved behind the workflow tasks provider during the
        # DDD/Hex refactor (components.workflow.application.providers); the old
        # infrastructure.persistence.workspaces.workflows.views.workflow_run_start
        # path no longer exists. Stub the provider's enqueue so no Celery task
        # is actually dispatched.
        monkeypatch.setattr(
            "components.workflow.application.providers.workflow_tasks_provider"
            ".WorkflowTasksProvider.enqueue_run_start",
            lambda _self, _run_id: None,
        )

        api_client.force_authenticate(user=workspace.workspace_owner)
        payload = {
            "trigger_type": "manual_start",
            "targets": [{"target_type": "group", "target_id": str(workspace.id)}],
        }
        response = api_client.post(
            f"/workspaces/workflows/workflows/{workflow.id}/runs/",
            payload,
            format="json",
        )

        assert response.status_code == 202
        assert response.data["queued"] is True
        assert response.data["run_ids"]

    def test_run_create_requires_auth(self, api_client, workspace_factory):
        workspace = workspace_factory()
        workflow = Workflow.objects.create(
            workspace=workspace,
            name="Run guard",
            goal="sponsorship",
            graph={"nodes": [{"id": "start", "type": "start", "title": "Start"}], "edges": []},
        )

        payload = {
            "trigger_type": "manual_start",
            "targets": [{"target_type": "group", "target_id": str(workspace.id)}],
        }
        response = api_client.post(
            f"/workspaces/workflows/workflows/{workflow.id}/runs/",
            payload,
            format="json",
        )

        assert response.status_code in (401, 403)
        assert set(response.data.keys()) == {"detail", "code", "fields"}

    def test_run_create_validation_returns_error_envelope(self, api_client, workspace_factory):
        workspace = workspace_factory()
        workflow = Workflow.objects.create(
            workspace=workspace,
            name="Run validation",
            goal="sponsorship",
            graph={"nodes": [{"id": "start", "type": "start", "title": "Start"}], "edges": []},
        )

        api_client.force_authenticate(user=workspace.workspace_owner)
        response = api_client.post(
            f"/workspaces/workflows/workflows/{workflow.id}/runs/",
            {"trigger_type": "manual_start"},
            format="json",
        )

        assert response.status_code == 400
        assert set(response.data.keys()) == {"detail", "code", "fields"}
        assert "targets" in response.data["fields"]
