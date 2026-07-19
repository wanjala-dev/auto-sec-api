"""Integration test: ``PaymentSucceeded`` (donor context) → "Thank donor"
Task.

Action List item P1 #21 — the second specialist to ship via the
Phase 3 ``SubscriptionRegistry``. Validates cross-context subscription
(payments → agents) and the donor-context filter
(only ``donation`` / ``sponsorship`` trigger; campaign / event / shop
are skipped).

Post-Phase-5 (Agents-as-Teammates migration retired ``AIAction``):
each finding lands as a Kanban Task carrying narrative on
``Task.description`` and detector context on ``Task.metadata``.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from components.agents.application.handlers.sponsorship_specialist_handler import (
    ACTION_TYPE,
    AGENT_TYPE,
    DETECTOR_KEY,
    handle_donor_payment_succeeded,
)
from components.payments.domain.events import PaymentSucceeded


def _build_event(
    *,
    workspace_id: str | UUID,
    payment_event_id: UUID | None = None,
    context: str = "donation",
    amount: str = "100.00",
    payer_name: str = "Jane Doe",
    recipient_name: str = "",
    campaign_id: str = "",
) -> PaymentSucceeded:
    return PaymentSucceeded(
        payment_event_id=payment_event_id or uuid4(),
        workspace_id=str(workspace_id),
        provider="stripe",
        event_type="payment_intent.succeeded",
        context=context,
        amount=amount,
        currency="USD",
        payer_name=payer_name,
        payer_email="jane@example.test",
        recipient_id="",
        recipient_name=recipient_name,
        project_id="",
        campaign_id=campaign_id,
        event_id="",
        metadata={},
    )


@pytest.mark.django_db
class TestSponsorshipSpecialistHandlerDonorContexts:
    def test_creates_thank_donor_task_for_donation_context(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id,
            payer_name="Jane Doe",
            amount="250.00",
        )

        handle_donor_payment_succeeded(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            )
        )
        assert len(tasks) == 1
        task = tasks[0]
        assert task.metadata["action_type"] == ACTION_TYPE
        assert task.metadata["agent_type"] == AGENT_TYPE
        assert task.metadata["context"]["detector_key"] == DETECTOR_KEY
        assert task.metadata["context"]["payment_event_id"] == str(
            event.payment_event_id
        )
        assert task.metadata["context"]["donor_context"] == "donation"

        assert "Thank Jane Doe" in task.title
        assert "$250.00" in task.title

    def test_creates_task_for_sponsorship_context(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id,
            context="sponsorship",
            recipient_name="Amani",
            amount="40.00",
        )

        handle_donor_payment_succeeded(event)

        tasks = list(
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            )
        )
        assert len(tasks) == 1
        assert tasks[0].metadata["context"]["donor_context"] == "sponsorship"
        # Recipient name surfaces in the description so the operator knows
        # the earmark.
        assert "Amani" in tasks[0].description


@pytest.mark.django_db
class TestSponsorshipSpecialistHandlerSkippedContexts:
    @pytest.mark.parametrize(
        "context", ["campaign", "event", "shop", "", "unknown"]
    )
    def test_non_donor_context_is_skipped(self, workspace_factory, context):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(
            workspace_id=workspace.id, context=context
        )

        handle_donor_payment_succeeded(event)

        # Non-donor contexts don't create thank-donor tasks; the
        # specialist is silent for those flows.
        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 0
        )


@pytest.mark.django_db
class TestSponsorshipSpecialistHandlerIdempotency:
    def test_replayed_event_is_idempotent_on_payment_event_id(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = _build_event(workspace_id=workspace.id)

        handle_donor_payment_succeeded(event)
        handle_donor_payment_succeeded(event)

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 1
        )

    def test_two_distinct_payments_create_two_tasks(
        self, workspace_factory
    ):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        handle_donor_payment_succeeded(
            _build_event(workspace_id=workspace.id, payment_event_id=uuid4())
        )
        handle_donor_payment_succeeded(
            _build_event(workspace_id=workspace.id, payment_event_id=uuid4())
        )

        assert (
            Task.objects.filter(
                workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
            ).count()
            == 2
        )


@pytest.mark.django_db
class TestSponsorshipSpecialistHandlerWorkspaceResolution:
    def test_missing_workspace_id_is_skipped(self):
        # No assertion needed beyond "doesn't raise" — the handler logs
        # and returns when workspace_id is empty.
        handle_donor_payment_succeeded(
            _build_event(workspace_id="")
        )

    def test_invalid_workspace_uuid_is_skipped(self):
        handle_donor_payment_succeeded(
            _build_event(workspace_id="not-a-uuid")
        )

    def test_unknown_workspace_uuid_is_skipped(self):
        from infrastructure.persistence.project.models import Task

        # Real UUID format but workspace doesn't exist.
        handle_donor_payment_succeeded(
            _build_event(workspace_id=uuid4())
        )

        assert Task.objects.filter(source_type=f"ai.{ACTION_TYPE}").count() == 0


@pytest.mark.django_db
class TestSponsorshipSpecialistHandlerAnonymousDonor:
    def test_anonymous_donor_uses_fallback_label(self, workspace_factory):
        from infrastructure.persistence.project.models import Task

        workspace = workspace_factory()
        event = PaymentSucceeded(
            payment_event_id=uuid4(),
            workspace_id=str(workspace.id),
            provider="stripe",
            event_type="payment_intent.succeeded",
            context="donation",
            amount="10.00",
            currency="USD",
            payer_name="",
            payer_email="",
        )

        handle_donor_payment_succeeded(event)

        task = Task.objects.filter(
            workspace=workspace, source_type=f"ai.{ACTION_TYPE}"
        ).first()
        assert task is not None
        # Title still meaningful — "Thank anonymous donor"
        assert "anonymous" in task.title.lower()
