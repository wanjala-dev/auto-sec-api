"""Integration tests for the budget receipt-accountability workflow.

The flow (uses the existing engine — no new node types):

    start (transaction_recorded)
      -> wait_until(event=receipt_attached, timeout)
           -> yes (receipt arrived)  -> end          [NO reminder]
           -> no  (timed out)        -> message(email) -> end  [reminder]

Correlation key = the TRANSACTION id (the run targets the transaction, not a
contact). The reminder email resolves its recipient from the trigger payload's
``owner_email`` (node_actions ``_send_email_message`` fallback).

These assert the engine, the autonomous wait_until both ways, the owner-email
delivery, and the trigger-completeness contract (catalog + bindable).
"""

from __future__ import annotations

import uuid

import pytest

from components.workflow.domain.constants import SOURCE_TYPES, TRIGGER_CATALOG
from components.workflow.infrastructure.adapters.dispatcher import dispatch_event
from components.workflow.infrastructure.tasks.workflow_tasks import workflow_run_start
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStepEvent,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db


# --- the receipt-accountability graph (mirrors the seeded system template) --
def _receipt_accountability_graph(timeout_seconds=604800):
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Expense recorded",
             "config": {"triggerType": "transaction_recorded"}},
            {"id": "wait_receipt", "type": "wait_until", "label": "Wait for receipt",
             "config": {"event": "receipt_attached", "timeout_seconds": timeout_seconds}},
            {"id": "remind", "type": "message", "label": "Receipt reminder",
             "config": {"channel": "email", "subject": "Please attach a receipt",
                        "body": "An expense you recorded is missing its receipt."}},
            {"id": "end", "type": "end", "label": "End"},
        ],
        "edges": [
            {"id": "ra-0", "from": "start", "to": "wait_receipt"},
            {"id": "ra-1", "from": "wait_receipt", "to": "end", "label": "yes"},
            {"id": "ra-2", "from": "wait_receipt", "to": "remind", "label": "no"},
            {"id": "ra-3", "from": "remind", "to": "end"},
        ],
    }


def _make_workflow(workspace):
    return Workflow.objects.create(
        workspace=workspace,
        name="Receipt accountability",
        goal="general",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph=_receipt_accountability_graph(),
    )


def _state(run, node_id):
    return WorkflowStepState.objects.filter(run=run, node_id=node_id).first()


def _branch_outcome(run, node_id):
    evt = WorkflowStepEvent.objects.filter(
        run=run, node_id=node_id, event_type="branched"
    ).first()
    return evt.payload if evt else None


# --- email boundary stub (the only thing stubbed; never the workflow code) ---
class _CapturingEmailAdapter:
    def __init__(self, *, result=True):
        self.result = result
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return self.result

    def send_templated(self, **kwargs):  # pragma: no cover - unused
        return self.result


class _CapturingProvider:
    def __init__(self, adapter):
        self._adapter = adapter

    def adapter(self):
        return self._adapter


def _patch_email(monkeypatch, adapter):
    from components.shared_platform.application.providers import email_adapter_provider

    monkeypatch.setattr(
        email_adapter_provider,
        "get_email_adapter_provider",
        lambda: _CapturingProvider(adapter),
    )


# --- (a) receipt arrives in time -> Yes -> end, NO reminder ----------------
class TestReceiptArrivesEarly:
    def test_receipt_attached_resolves_yes_no_email(self, workspace_factory, monkeypatch):
        adapter = _CapturingEmailAdapter()
        _patch_email(monkeypatch, adapter)

        workspace = workspace_factory()
        wf = _make_workflow(workspace)
        transaction_id = str(uuid.uuid4())

        # Arm the wait_until exactly as the engine does on first entry (avoids
        # eager-Celery's synchronous timeout so we can deliver the event first).
        run = WorkflowRun.objects.create(
            workflow=wf,
            workflow_version=1,
            status=WorkflowRun.Status.RUNNING,
            trigger_type="transaction_recorded",
            trigger_payload={"owner_email": "owner@example.org", "transaction_id": transaction_id},
            target_type="contact",
            target_id=transaction_id,
            current_node_id="wait_receipt",
        )
        WorkflowStepState.objects.create(
            run=run, node_id="wait_receipt", status="waiting",
            output={"awaiting_event": "receipt_attached"},
        )

        # The receipt_attached event arrives for the SAME transaction id.
        event = WorkflowEvent.objects.create(
            workspace=workspace,
            source_type="receipt",
            trigger_type="receipt_attached",
            payload={"target_id": transaction_id, "transaction_id": transaction_id},
        )
        dispatch_event(event)

        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.COMPLETED
        assert _branch_outcome(run, "wait_receipt")["outcome"] is True
        assert _state(run, "end").status == "completed"
        assert _state(run, "remind") is None       # reminder node never ran
        assert adapter.sent == []                   # and no email went out


# --- (b) no receipt within window -> No -> reminder email to the owner ------
class TestReceiptTimesOut:
    def test_timeout_emails_owner_reminder(self, workspace_factory, monkeypatch):
        # Eager Celery ignores the wait_until countdown, so the scheduled timeout
        # fires synchronously -> No branch -> the message node sends the email.
        adapter = _CapturingEmailAdapter()
        _patch_email(monkeypatch, adapter)

        wf = _make_workflow(workspace_factory())
        transaction_id = str(uuid.uuid4())
        run = WorkflowRun.objects.create(
            workflow=wf,
            workflow_version=1,
            status=WorkflowRun.Status.QUEUED,
            trigger_type="transaction_recorded",
            trigger_payload={"owner_email": "owner@example.org", "transaction_id": transaction_id},
            target_type="contact",
            target_id=transaction_id,
        )

        workflow_run_start.delay(str(run.id))

        run.refresh_from_db()
        assert run.status == WorkflowRun.Status.COMPLETED
        assert _branch_outcome(run, "wait_receipt")["outcome"] is False
        assert _state(run, "remind").status == "completed"
        # The reminder reached the expense owner resolved from owner_email.
        assert len(adapter.sent) == 1
        assert adapter.sent[0].to == ["owner@example.org"]


# --- trigger-completeness contract (catalog + bindable) --------------------
class TestTriggerCompleteness:
    def test_triggers_in_catalog_with_source_types(self):
        by_id = {t.id: t for t in TRIGGER_CATALOG}
        assert by_id["transaction_recorded"].source_type == "budget"
        assert by_id["receipt_attached"].source_type == "receipt"
        assert "budget" in SOURCE_TYPES
        assert "receipt" in SOURCE_TYPES

    def _binding_valid(self, workflow, *, source_type, trigger_type):
        from components.workflow.mappers.rest.workflow_serializers import (
            WorkflowBindingSerializer,
        )

        serializer = WorkflowBindingSerializer(
            data={
                "workflow_id": str(workflow.id),
                "source_type": source_type,
                "trigger_type": trigger_type,
                "source_id": "",
                "is_active": True,
            }
        )
        return serializer.is_valid(), serializer.errors

    def test_transaction_recorded_binding_accepted(self, workspace_factory):
        wf = _make_workflow(workspace_factory())
        ok, errors = self._binding_valid(
            wf, source_type="budget", trigger_type="transaction_recorded"
        )
        assert ok, errors

    def test_receipt_attached_binding_accepted(self, workspace_factory):
        wf = _make_workflow(workspace_factory())
        ok, errors = self._binding_valid(
            wf, source_type="receipt", trigger_type="receipt_attached"
        )
        assert ok, errors
