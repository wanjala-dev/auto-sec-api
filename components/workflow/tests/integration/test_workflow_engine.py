"""Integration tests for the autonomous workflow execution engine.

These exercise the full Celery chain (eager in tests): linear advance,
autonomous condition branching both ways, wait_until timeout -> No and
event -> Yes, loud action failure, and enrollment -> run wiring. Before this
suite the run engine had zero direct tests (the single biggest coverage hole).
"""

from __future__ import annotations

import uuid

import pytest

from components.workflow.application.service import WorkflowService
from components.workflow.infrastructure.adapters.dispatcher import dispatch_event
from components.workflow.infrastructure.tasks import workflow_tasks
from components.workflow.infrastructure.tasks.workflow_tasks import (
    workflow_run_start,
    workflow_wait_until_resolve,
)
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowEnrollment,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStepEvent,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db


# --- graph builders --------------------------------------------------------
def _condition_graph(predicate):
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "cond", "type": "condition", "label": "Gave a lot?", "config": {"predicate": predicate}},
            {"id": "yes_end", "type": "end", "label": "Major donor"},
            {"id": "no_end", "type": "end", "label": "Regular"},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "cond"},
            {"id": "e2", "from": "cond", "to": "yes_end", "label": "yes"},
            {"id": "e3", "from": "cond", "to": "no_end", "label": "no"},
        ],
    }


def _wait_until_graph(timeout_seconds=3600):
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {
                "id": "wu",
                "type": "wait_until",
                "label": "Wait for donation",
                "config": {"event": "donation_received", "timeout_seconds": timeout_seconds},
            },
            {"id": "yes_end", "type": "end", "label": "Donated"},
            {"id": "no_end", "type": "end", "label": "Lapsed"},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "wu"},
            {"id": "e2", "from": "wu", "to": "yes_end", "label": "yes"},
            {"id": "e3", "from": "wu", "to": "no_end", "label": "no"},
        ],
    }


def _action_graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "act", "type": "message", "label": "Send thanks", "config": {"channel": "email", "body": "hi"}},
            {"id": "end", "type": "end", "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "act"},
            {"id": "e2", "from": "act", "to": "end"},
        ],
    }


def _make_workflow(workspace, graph):
    return Workflow.objects.create(
        workspace=workspace,
        name="Test flow",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph=graph,
    )


def _make_run(workflow, payload=None, target_id=None):
    return WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=WorkflowRun.Status.QUEUED,
        trigger_type="manual",
        trigger_payload=payload or {},
        target_type="contact",
        target_id=target_id or str(uuid.uuid4()),
    )


def _state(run, node_id):
    return WorkflowStepState.objects.filter(run=run, node_id=node_id).first()


def _branch_outcome(run, node_id):
    evt = WorkflowStepEvent.objects.filter(run=run, node_id=node_id, event_type="branched").first()
    return evt.payload if evt else None


# --- condition branching ---------------------------------------------------
class TestConditionBranching:
    def test_condition_true_takes_yes_branch(self, workspace_factory):
        wf = _make_workflow(workspace_factory(), _condition_graph({"field": "amount", "op": "gte", "value": 500}))
        run = _make_run(wf, payload={"amount": 750})

        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.COMPLETED
        assert _branch_outcome(run, "cond")["outcome"] is True
        assert _state(run, "yes_end").status == "completed"
        assert _state(run, "no_end") is None

    def test_condition_false_takes_no_branch(self, workspace_factory):
        wf = _make_workflow(workspace_factory(), _condition_graph({"field": "amount", "op": "gte", "value": 500}))
        run = _make_run(wf, payload={"amount": 100})

        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.COMPLETED
        assert _branch_outcome(run, "cond")["outcome"] is False
        assert _state(run, "no_end").status == "completed"
        assert _state(run, "yes_end") is None

    def test_malformed_predicate_fails_run(self, workspace_factory):
        wf = _make_workflow(workspace_factory(), _condition_graph({"match": "xor", "conditions": [{"field": "a", "op": "eq", "value": 1}]}))
        run = _make_run(wf, payload={"a": 1})

        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.FAILED
        assert _state(run, "cond").status == "failed"


# --- wait_until ------------------------------------------------------------
class TestWaitUntil:
    def test_timeout_branches_no(self, workspace_factory):
        # Eager Celery ignores countdown, so the scheduled timeout fires
        # synchronously and the run resolves down the No (timed-out) branch.
        wf = _make_workflow(workspace_factory(), _wait_until_graph())
        run = _make_run(wf)

        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.COMPLETED
        assert _branch_outcome(run, "wu")["outcome"] is False
        assert _state(run, "no_end").status == "completed"

    def test_event_arrival_branches_yes(self, workspace_factory):
        workspace = workspace_factory()
        wf = _make_workflow(workspace, _wait_until_graph())
        target_id = str(uuid.uuid4())
        run = WorkflowRun.objects.create(
            workflow=wf,
            workflow_version=1,
            status=WorkflowRun.Status.RUNNING,
            trigger_type="manual",
            trigger_payload={},
            target_type="contact",
            target_id=target_id,
            current_node_id="wu",
        )
        # Simulate an armed wait_until (the engine sets this on first entry).
        WorkflowStepState.objects.create(
            run=run, node_id="wu", status="waiting", output={"awaiting_event": "donation_received"}
        )

        # The awaited event arrives for this target -> dispatcher wakes the step.
        event = WorkflowEvent.objects.create(
            workspace=workspace,
            source_type="sponsorship",
            trigger_type="donation_received",
            payload={"target_id": target_id, "amount": 50},
        )
        dispatch_event(event)

        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.COMPLETED
        assert _branch_outcome(run, "wu")["outcome"] is True
        assert _state(run, "yes_end").status == "completed"

    def test_resolve_is_noop_if_not_waiting(self, workspace_factory):
        wf = _make_workflow(workspace_factory(), _wait_until_graph())
        run = WorkflowRun.objects.create(
            workflow=wf, workflow_version=1, status=WorkflowRun.Status.RUNNING,
            trigger_type="manual", trigger_payload={}, target_type="contact",
            target_id=str(uuid.uuid4()), current_node_id="wu",
        )
        WorkflowStepState.objects.create(run=run, node_id="wu", status="completed")
        # No waiting state -> resolve must not branch.
        workflow_wait_until_resolve.delay(str(run.id), "wu")
        run.refresh_from_db()
        assert _branch_outcome(run, "wu") is None


# --- action failure (fail loudly) -----------------------------------------
class TestActionFailure:
    def test_action_exception_fails_run_loudly(self, workspace_factory, monkeypatch):
        wf = _make_workflow(workspace_factory(), _action_graph())
        run = _make_run(wf)

        def _boom(run_, node, config):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(workflow_tasks, "execute_node_action", _boom)
        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.FAILED
        assert _state(run, "act").status == "failed"
        assert WorkflowStepEvent.objects.filter(run=run, node_id="act", event_type="failed").exists()
        assert _state(run, "end") is None  # never advanced past the failure

    def test_action_returning_failed_dict_fails_run(self, workspace_factory, monkeypatch):
        wf = _make_workflow(workspace_factory(), _action_graph())
        run = _make_run(wf)

        monkeypatch.setattr(
            workflow_tasks, "execute_node_action",
            lambda run_, node, config: {"status": "failed", "error": "bounced"},
        )
        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.FAILED

    def test_action_success_advances(self, workspace_factory, monkeypatch):
        wf = _make_workflow(workspace_factory(), _action_graph())
        run = _make_run(wf)

        monkeypatch.setattr(
            workflow_tasks, "execute_node_action",
            lambda run_, node, config: {"status": "sent"},
        )
        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert run.status == WorkflowRun.Status.COMPLETED
        assert _state(run, "act").status == "completed"
        assert _state(run, "end").status == "completed"


# --- enrollment -> run -----------------------------------------------------
class TestEnrollmentStartsRun:
    def test_enroll_creates_enrollment_and_run(self, workspace_factory):
        wf = _make_workflow(workspace_factory(), _condition_graph({"field": "amount", "op": "gte", "value": 1}))
        target_id = str(uuid.uuid4())

        result = WorkflowService().enroll_targets(
            workflow=wf, targets=[{"target_type": "contact", "target_id": target_id}]
        )

        assert len(result["run_ids"]) == 1
        assert WorkflowEnrollment.objects.filter(
            workflow=wf, target_id=target_id, status="active"
        ).exists()
        run = WorkflowRun.objects.get(id=result["run_ids"][0])
        assert run.trigger_type == "manual_enroll"

        # Starting that run drives it through the engine.
        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.COMPLETED

    def test_enroll_is_idempotent(self, workspace_factory):
        wf = _make_workflow(workspace_factory(), _condition_graph({"field": "amount", "op": "gte", "value": 1}))
        target = {"target_type": "contact", "target_id": str(uuid.uuid4())}

        first = WorkflowService().enroll_targets(workflow=wf, targets=[target])
        second = WorkflowService().enroll_targets(workflow=wf, targets=[target])

        assert first["run_ids"] == second["run_ids"]  # same run reused
        assert WorkflowEnrollment.objects.filter(workflow=wf).count() == 1
