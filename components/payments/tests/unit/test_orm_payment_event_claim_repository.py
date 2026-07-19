from __future__ import annotations

import pytest

from components.payments.infrastructure.repositories.orm_payment_event_claim_repository import (
    OrmPaymentEventClaimRepository,
)
from infrastructure.persistence.workspaces.payments.models import PaymentEvent

pytestmark = pytest.mark.django_db


def test_claim_event_marks_payment_event_processing_once():
    event = PaymentEvent.objects.create(provider="stripe", event_id="evt_claim_repo")
    repository = OrmPaymentEventClaimRepository()

    claimed = repository.claim_event(
        payment_event_id=event.id,
        claimed_by="test-suite",
        message="Claimed by repository.",
    )

    event.refresh_from_db()
    assert claimed is True
    assert event.status == PaymentEvent.STATUS_PROCESSING
    assert event.status_message == "Claimed by repository."
