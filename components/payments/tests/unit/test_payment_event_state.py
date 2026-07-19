from __future__ import annotations

import pytest

from components.payments.infrastructure.adapters.payment_event_state import (
    claim_payment_event_processing,
    mark_payment_event_processed,
    mark_payment_event_processing,
    payment_event_is_processable_for_worker,
)
from infrastructure.persistence.workspaces.payments.models import PaymentEvent

pytestmark = pytest.mark.django_db


def test_claim_payment_event_processing_is_idempotent():
    event = PaymentEvent.objects.create(provider="stripe", event_id="evt_claim_test")

    assert claim_payment_event_processing(event, "claimed") is True
    event.refresh_from_db()
    assert event.status == PaymentEvent.STATUS_PROCESSING

    duplicate = PaymentEvent.objects.get(id=event.id)
    assert claim_payment_event_processing(duplicate, "claimed-again") is False


def test_mark_payment_event_processing_and_processed_updates_status_fields():
    event = PaymentEvent.objects.create(provider="stripe", event_id="evt_state_test")

    mark_payment_event_processing(event, "processing")
    event.refresh_from_db()
    assert event.status == PaymentEvent.STATUS_PROCESSING
    assert payment_event_is_processable_for_worker(event) is True

    mark_payment_event_processed(event, PaymentEvent.STATUS_PROCESSED, "done")
    event.refresh_from_db()
    assert event.status == PaymentEvent.STATUS_PROCESSED
    assert event.status_message == "done"
    assert event.processed_at is not None
    assert payment_event_is_processable_for_worker(event) is False
