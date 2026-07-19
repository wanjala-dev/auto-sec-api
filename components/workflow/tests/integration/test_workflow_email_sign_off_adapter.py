"""Unit coverage for the WorkflowEmail sign-off adapter.

The adapter maps the sign-off kernel onto a parked ``WorkflowStepState`` row
(``output["signoff"]`` blob) — no new model. These build a parked step directly
and assert the receipts, state round-trip, and target.
"""

from __future__ import annotations

import pytest

from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.sign_off_target import Audience
from components.workflow.infrastructure.adapters.workflow_email_sign_off_adapter import (
    WorkflowEmailSignOffAdapter,
)
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowRun,
    WorkflowStepState,
)

pytestmark = pytest.mark.django_db


def _parked_step(workspace, *, content="", grounding=None, audience="internal_team", review_state="pending"):
    workflow = Workflow.objects.create(
        workspace=workspace,
        name="flow",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph={"nodes": [], "edges": []},
    )
    run = WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=WorkflowRun.Status.PAUSED,
        trigger_type="manual",
        trigger_payload={},
        target_type="contact",
        target_id="someone@example.com",
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
                "audience": audience,
                "subject": "Subject",
                "content": content,
                "grounding": list(grounding or []),
            }
        },
    )


def test_artifact_type_is_workflow_email():
    assert WorkflowEmailSignOffAdapter().artifact_type() == "workflow_email"


def test_get_set_state_round_trip(workspace_factory):
    step = _parked_step(workspace_factory())
    adapter = WorkflowEmailSignOffAdapter()
    artifact_id = str(step.id)

    assert adapter.get_state(artifact_id) == ReviewState.PENDING

    adapter.set_state(artifact_id, ReviewState.APPROVED)
    step.refresh_from_db()
    assert adapter.get_state(artifact_id) == ReviewState.APPROVED
    # Approval completes the step and stamps completed_at.
    assert step.status == "completed"
    assert step.completed_at is not None


def test_set_state_changes_requested_keeps_step_parked(workspace_factory):
    step = _parked_step(workspace_factory())
    adapter = WorkflowEmailSignOffAdapter()
    artifact_id = str(step.id)

    adapter.set_state(artifact_id, ReviewState.CHANGES_REQUESTED)
    step.refresh_from_db()
    assert adapter.get_state(artifact_id) == ReviewState.CHANGES_REQUESTED
    assert step.status == "waiting_input"


def test_set_state_rejected_fails_step(workspace_factory):
    step = _parked_step(workspace_factory())
    adapter = WorkflowEmailSignOffAdapter()
    artifact_id = str(step.id)

    adapter.set_state(artifact_id, ReviewState.REJECTED)
    step.refresh_from_db()
    assert adapter.get_state(artifact_id) == ReviewState.REJECTED
    assert step.status == "failed"


def test_build_receipts_maps_invented_figure_to_unverifiable(workspace_factory):
    # The AI body asserts $999,999 but the grounding has no such number -> it
    # surfaces as an UNVERIFIABLE figure (amber), not a contradiction.
    step = _parked_step(
        workspace_factory(),
        content="Thanks to you we raised $999,999 this quarter.",
        grounding=["total raised 100"],
    )
    receipts = WorkflowEmailSignOffAdapter().build_receipts(str(step.id))

    assert len(receipts.figure_checks) >= 1
    fc = receipts.figure_checks[0]
    assert fc.unverifiable is True
    assert fc.contradicted is False
    assert receipts.unverifiable_figures
    assert not receipts.contradicted_figures


def test_build_receipts_clean_when_figures_grounded(workspace_factory):
    step = _parked_step(
        workspace_factory(),
        content="We raised $100 this quarter.",
        grounding=["100"],
    )
    receipts = WorkflowEmailSignOffAdapter().build_receipts(str(step.id))
    assert receipts.is_clean


def test_target_external_recipient_escalates(workspace_factory):
    external = _parked_step(workspace_factory(), audience="external")
    internal = _parked_step(workspace_factory(), audience="internal_team")
    adapter = WorkflowEmailSignOffAdapter()

    ext_target = adapter.target(str(external.id))
    assert ext_target.audience == Audience.EXTERNAL
    assert ext_target.escalates is True

    int_target = adapter.target(str(internal.id))
    assert int_target.audience == Audience.INTERNAL_TEAM
