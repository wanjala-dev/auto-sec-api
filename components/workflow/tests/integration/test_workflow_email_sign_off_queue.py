"""Queue-surface coverage for the WorkflowEmail sign-off adapter (Phase 6a):
``list_pending`` returns parked AI-email steps, and ``approve`` sends the email
(reusing the message-node executor) then RESUMES the run (advances past the
parked node). The send + the task enqueue are stubbed at the boundary so no real
email is sent and no real Celery task runs.
"""

from __future__ import annotations

import pytest

from components.sign_off.domain.value_objects.review_state import ReviewState
from components.workflow.infrastructure.adapters import workflow_email_sign_off_adapter as adapter_mod
from components.workflow.infrastructure.adapters import node_actions as node_actions_mod
from components.workflow.application.providers import workflow_tasks_provider as tasks_mod
from components.workflow.infrastructure.adapters.workflow_email_sign_off_adapter import (
    WorkflowEmailSignOffAdapter,
)
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db

_GRAPH = {
    "nodes": [
        {"id": "start", "type": "start"},
        {"id": "msg", "type": "message", "config": {"channel": "email", "body": "Hi {{name}}"}},
        {"id": "end", "type": "end"},
    ],
    "edges": [
        {"from": "start", "to": "msg"},
        {"from": "msg", "to": "end"},
    ],
}


def _parked_step(workspace, *, review_state="pending", subject="Impact update"):
    workflow = Workflow.objects.create(
        workspace=workspace,
        name="flow",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph=_GRAPH,
    )
    run = WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=WorkflowRun.Status.PAUSED,
        trigger_type="manual",
        trigger_payload={},
        target_type="contact",
        target_id="someone@example.com",
        current_node_id="msg",
    )
    return WorkflowStepState.objects.create(
        run=run,
        node_id="msg",
        status="waiting_input",
        output={
            "signoff": {
                "artifact_type": "workflow_email",
                "review_state": review_state,
                "node_id": "msg",
                "recipient_email": "someone@example.com",
                "audience": "external",
                "subject": subject,
                "content": "<p>We raised funds</p>",
                "grounding": [],
            }
        },
    )


class _TasksSpy:
    def __init__(self):
        self.steps = []
        self.completes = []

    def enqueue_run_step(self, run_id, node_id):
        self.steps.append((run_id, node_id))

    def enqueue_run_complete(self, run_id):
        self.completes.append(run_id)


def test_list_pending_returns_parked_ai_email_steps(workspace_factory):
    ws = workspace_factory()
    step = _parked_step(ws, subject="Q3 impact")

    items = WorkflowEmailSignOffAdapter().list_pending(str(ws.id))

    assert [it.artifact_id for it in items] == [str(step.id)]
    assert items[0].title == "Q3 impact"
    assert items[0].artifact_type == "workflow_email"


def test_approve_sends_email_and_resumes_run(workspace_factory, monkeypatch):
    ws = workspace_factory()
    step = _parked_step(ws)

    sends = []
    monkeypatch.setattr(
        node_actions_mod,
        "execute_node_action",
        lambda run, node, config: sends.append(node.get("id")) or {"channel": "email", "status": "sent"},
    )
    spy = _TasksSpy()
    monkeypatch.setattr(tasks_mod, "_default", spy)

    WorkflowEmailSignOffAdapter().approve(str(step.id), actor_id="7")

    # 1. The email was sent via the reused message-node executor.
    assert sends == ["msg"]
    # 2. The step is completed + the approval recorded on the signoff blob.
    step.refresh_from_db()
    assert step.status == "completed"
    assert step.output["signoff"]["review_state"] == "approved"
    # 3. The run resumed and advanced to the next node, enqueuing it.
    step.run.refresh_from_db()
    assert step.run.current_node_id == "end"
    assert step.run.status == WorkflowRun.Status.RUNNING
    assert spy.steps == [(str(step.run.id), "end")]


def test_reject_fails_step_and_does_not_send(workspace_factory, monkeypatch):
    ws = workspace_factory()
    step = _parked_step(ws)
    sends = []
    monkeypatch.setattr(
        node_actions_mod, "execute_node_action", lambda *a, **k: sends.append(1)
    )

    WorkflowEmailSignOffAdapter().reject(str(step.id), actor_id="7")

    step.refresh_from_db()
    assert step.status == "failed"
    assert WorkflowEmailSignOffAdapter().get_state(str(step.id)) == ReviewState.REJECTED
    assert sends == []  # rejection never sends


def test_request_changes_keeps_step_parked(workspace_factory):
    ws = workspace_factory()
    step = _parked_step(ws)

    WorkflowEmailSignOffAdapter().request_changes(str(step.id), actor_id="7", note="fix figure")

    step.refresh_from_db()
    assert step.status == "waiting_input"
    assert WorkflowEmailSignOffAdapter().get_state(str(step.id)) == ReviewState.CHANGES_REQUESTED
