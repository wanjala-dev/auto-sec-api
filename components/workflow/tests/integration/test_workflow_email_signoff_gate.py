"""Phase 3 sign-off gate — AI workflow-email content can never auto-send.

The firm, non-negotiable deliverable: an AI-derived workflow email parks pending
a human sign-off and is NOT sent; a deterministic template email sends exactly
as before. These drive the full Celery chain (eager in tests) via
``workflow_run_start``, stubbing only the email boundary (never the workflow
code itself).
"""

from __future__ import annotations

import uuid

import pytest

from components.sign_off.application.providers.sign_off_registry_provider import (
    get_sign_off_registry,
)
from components.sign_off.domain.errors import NotApprovedError
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.workflow.infrastructure.adapters.workflow_email_sign_off_adapter import (
    WorkflowEmailSignOffAdapter,
)
from components.workflow.infrastructure.tasks.workflow_tasks import workflow_run_start
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db


# --- email boundary stub (the ONLY stub allowed) ---------------------------
class _CapturingEmailAdapter:
    def __init__(self, *, result=True):
        self.result = result
        self.sent = []

    def send(self, message):
        self.sent.append(message)
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


# --- graph builders --------------------------------------------------------
def _message_graph(message_config):
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "msg", "type": "message", "label": "Send email", "config": message_config},
            {"id": "end", "type": "end", "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "msg"},
            {"id": "e2", "from": "msg", "to": "end"},
        ],
    }


def _ai_then_message_graph(message_config):
    """An ``ai`` node feeding a message node — the chaining signal, no marker."""
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            # Empty config -> the ai executor is a no-op (skipped); its mere
            # presence in the graph is the chaining signal classification reads.
            {"id": "ai", "type": "ai", "label": "Draft", "config": {}},
            {"id": "msg", "type": "message", "label": "Send email", "config": message_config},
            {"id": "end", "type": "end", "label": "Done"},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "ai"},
            {"id": "e2", "from": "ai", "to": "msg"},
            {"id": "e3", "from": "msg", "to": "end"},
        ],
    }


def _workflow(workspace, graph):
    return Workflow.objects.create(
        workspace=workspace,
        name="Email flow",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph=graph,
    )


def _run(workflow, target_id, payload=None):
    return WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=WorkflowRun.Status.QUEUED,
        trigger_type="manual",
        trigger_payload=payload or {},
        target_type="contact",
        target_id=target_id,
    )


def _msg_state(run):
    return WorkflowStepState.objects.filter(run=run, node_id="msg").first()


# --- deterministic email: behaviour unchanged ------------------------------
class TestDeterministicEmailSends:
    def test_deterministic_template_email_is_sent(self, workspace_factory, user_factory, monkeypatch):
        adapter = _CapturingEmailAdapter()
        _patch_email(monkeypatch, adapter)

        ws = workspace_factory()
        contact = user_factory(email="donor@example.com")
        config = {"channel": "email", "subject": "Thank you", "body": "Thanks for your gift!"}
        run = _run(_workflow(ws, _message_graph(config)), str(contact.id))

        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        # Sends exactly as today and the run completes.
        assert len(adapter.sent) == 1
        assert adapter.sent[0].to == ["donor@example.com"]
        assert run.status == WorkflowRun.Status.COMPLETED
        assert _msg_state(run).status == "completed"


# --- AI email: fail-safe park, never sent ----------------------------------
class TestAiEmailParksAndDoesNotSend:
    def test_explicit_ai_marker_parks_without_sending(self, workspace_factory, user_factory, monkeypatch):
        get_sign_off_registry().register(WorkflowEmailSignOffAdapter())
        adapter = _CapturingEmailAdapter()
        _patch_email(monkeypatch, adapter)

        ws = workspace_factory()
        contact = user_factory(email="donor@example.com")
        # AI-marked content with an invented figure; grounding (payload) is empty.
        config = {
            "channel": "email",
            "subject": "Your impact",
            "body": "Thanks to you we raised $999,999 this quarter.",
            "ai_generated": True,
        }
        run = _run(_workflow(ws, _message_graph(config)), str(contact.id))

        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        # The email was NOT sent, the run is PAUSED, the step parked pending.
        assert adapter.sent == []
        assert run.status == WorkflowRun.Status.PAUSED
        state = _msg_state(run)
        assert state.status == "waiting_input"
        assert state.output["signoff"]["artifact_type"] == "workflow_email"

        # A pending workflow_email sign-off artifact exists; require_approved
        # blocks any send until a human signs off.
        artifact_id = str(state.id)
        assert get_sign_off_registry().get_adapter("workflow_email").get_state(
            artifact_id
        ) == ReviewState.PENDING
        with pytest.raises(NotApprovedError):
            from components.sign_off.application.services.require_approved import (
                require_approved,
            )

            require_approved("workflow_email", artifact_id)

    def test_ai_to_message_chaining_parks_without_marker(
        self, workspace_factory, user_factory, monkeypatch
    ):
        # No explicit marker — the message draws from an upstream ai node via a
        # {{steps.<ai>}} placeholder, which gates it by design.
        adapter = _CapturingEmailAdapter()
        _patch_email(monkeypatch, adapter)

        ws = workspace_factory()
        contact = user_factory(email="donor@example.com")
        config = {
            "channel": "email",
            "subject": "Update",
            "body": "{{steps.ai.result_preview}}",
        }
        run = _run(_workflow(ws, _ai_then_message_graph(config)), str(contact.id))

        workflow_run_start.delay(str(run.id))
        run.refresh_from_db()

        assert adapter.sent == []
        assert run.status == WorkflowRun.Status.PAUSED
        assert _msg_state(run).status == "waiting_input"
