"""Retry a failed run FROM the failed node (not a full restart).

retry_run resets the failed step to pending and points the run there; the
engine re-executes that node and continues, without re-running completed
upstream steps (so their side effects don't re-fire).
"""

from __future__ import annotations

import uuid

import pytest

from components.workflow.application.service import WorkflowService
from components.workflow.infrastructure.tasks import workflow_tasks
from components.workflow.infrastructure.tasks.workflow_tasks import (
    workflow_run_start,
    workflow_run_step,
)
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStepEvent,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db


def _action_graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "act", "type": "message", "label": "Send thanks",
             "config": {"channel": "email", "body": "hi"}},
            {"id": "end", "type": "end", "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "act"},
            {"id": "e2", "from": "act", "to": "end"},
        ],
    }


def _make_workflow(workspace):
    return Workflow.objects.create(
        workspace=workspace,
        name="Retry flow",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph=_action_graph(),
    )


def _make_run(workflow):
    return WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=WorkflowRun.Status.QUEUED,
        trigger_type="manual",
        trigger_payload={},
        target_type="contact",
        target_id=str(uuid.uuid4()),
    )


def _state(run, node_id):
    return WorkflowStepState.objects.filter(run=run, node_id=node_id).first()


class TestRetryStateTransitions:
    def test_retry_resets_failed_step_and_points_run_at_it(self, workspace_factory):
        wf = _make_workflow(workspace_factory())
        run = _make_run(wf)
        run.status = WorkflowRun.Status.FAILED
        run.current_node_id = "act"
        run.save(update_fields=["status", "current_node_id"])
        WorkflowStepState.objects.create(run=run, node_id="start", status="completed")
        WorkflowStepState.objects.create(
            run=run, node_id="act", status="failed", last_error="smtp down"
        )

        WorkflowService().retry_run(run)

        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.RUNNING
        assert run.current_node_id == "act"
        assert _state(run, "act").status == "pending"
        assert _state(run, "act").last_error == ""
        # Upstream completed step is untouched (not re-run).
        assert _state(run, "start").status == "completed"


class TestRetryResumesAndCompletes:
    def test_retry_reruns_failed_node_then_finishes(
        self, workspace_factory, monkeypatch
    ):
        wf = _make_workflow(workspace_factory())
        run = _make_run(wf)

        calls = []

        def _boom(run_, node, config):
            calls.append(node.get("id"))
            raise RuntimeError("smtp down")

        monkeypatch.setattr(workflow_tasks, "execute_node_action", _boom)
        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.FAILED
        assert _state(run, "act").status == "failed"
        assert calls == ["act"]  # only the action ran (and failed)

        # The dependency recovers; retry should re-run ONLY the failed node.
        succeeded = []

        def _ok(run_, node, config):
            succeeded.append(node.get("id"))
            return {"status": "ok"}

        monkeypatch.setattr(workflow_tasks, "execute_node_action", _ok)

        run = WorkflowService().retry_run(run)
        # Controller enqueues run_step at the resume node.
        workflow_run_step.delay(str(run.id), run.current_node_id)
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.COMPLETED
        assert _state(run, "act").status == "completed"
        assert _state(run, "end").status == "completed"
        # Retry re-ran the failed action exactly once; start was NOT re-executed.
        assert succeeded == ["act"]
        assert WorkflowStepEvent.objects.filter(
            run=run, node_id="act", event_type="completed"
        ).exists()
