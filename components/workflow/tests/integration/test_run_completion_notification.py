"""Integration tests: a finished workflow run notifies the workflow owner.

When a run completes or fails, the owner (Workflow.created_by) should get an
in-app Notification. A notification failure must never fail the run, and a
workflow with no owner must not crash the finalizer.
"""

from __future__ import annotations

import uuid

import pytest

from components.workflow.infrastructure.tasks.workflow_tasks import (
    _fail_run,
    workflow_run_complete,
)
from infrastructure.persistence.notifications.models import Notification
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db


def _graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "end", "type": "end", "label": "End"},
        ],
        "edges": [{"id": "start-end", "from": "start", "to": "end"}],
    }


def _make_workflow(workspace, owner=None):
    return Workflow.objects.create(
        workspace=workspace,
        name="Welcome Series",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph=_graph(),
        created_by=owner,
    )


def _make_run(workflow):
    return WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=WorkflowRun.Status.RUNNING,
        trigger_type="manual",
        trigger_payload={},
        target_type="contact",
        target_id=str(uuid.uuid4()),
    )


class TestRunCompletionNotification:
    def test_completion_notifies_owner(self, workspace_factory, user_factory, django_capture_on_commit_callbacks):
        owner = user_factory()
        wf = _make_workflow(workspace_factory(), owner=owner)
        run = _make_run(wf)

        # Notification delivery flows through the dispatcher funnel, which
        # enqueues post-commit — flush on_commit callbacks so eager Celery runs.
        with django_capture_on_commit_callbacks(execute=True):
            workflow_run_complete.delay(str(run.id))

        notes = Notification.objects.filter(recipient=owner)
        assert notes.count() == 1
        assert "completed" in notes.first().verb.lower()

    def test_failure_notifies_owner(self, workspace_factory, user_factory, django_capture_on_commit_callbacks):
        owner = user_factory()
        wf = _make_workflow(workspace_factory(), owner=owner)
        run = _make_run(wf)
        state = WorkflowStepState.objects.create(run=run, node_id="start", status="running")

        with django_capture_on_commit_callbacks(execute=True):
            _fail_run(run, state, "start", RuntimeError("boom"))

        notes = Notification.objects.filter(recipient=owner)
        assert notes.count() == 1
        assert "failed" in notes.first().verb.lower()
        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.FAILED

    def test_no_owner_does_not_crash_or_notify(self, workspace_factory):
        wf = _make_workflow(workspace_factory(), owner=None)
        run = _make_run(wf)

        # Should finalize cleanly without raising and without any notification.
        workflow_run_complete.delay(str(run.id))

        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.COMPLETED
        assert Notification.objects.count() == 0
