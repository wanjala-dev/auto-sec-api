from __future__ import annotations

from decimal import Decimal

import pytest

from components.payments.infrastructure.repositories.orm_payment_event_recording_repository import (
    OrmPaymentEventRecordingRepository,
)
from infrastructure.persistence.workspaces.payments.models import PaymentEvent

pytestmark = pytest.mark.django_db


def test_record_if_new_persists_and_reuses_existing_event():
    repository = OrmPaymentEventRecordingRepository()

    first = repository.record_if_new(
        provider="Stripe",
        provider_account_id="acct_123",
        provider_event_id="evt_123",
        external_id="in_123",
        event_type="invoice.payment_succeeded",
        workspace_id=None,
        method_id=None,
        amount=Decimal("19.00"),
        currency="USD",
        payload={"id": "evt_123", "object": "event"},
    )
    second = repository.record_if_new(
        provider="stripe",
        provider_account_id="acct_123",
        provider_event_id="evt_123",
        external_id="in_123",
        event_type="invoice.payment_succeeded",
        workspace_id=None,
        method_id=None,
        amount=Decimal("19.00"),
        currency="USD",
        payload={"id": "evt_123", "object": "event"},
    )

    assert first.is_new is True
    assert first.record is not None
    assert second.is_new is False
    assert second.record is not None
    assert second.record.id == first.record.id

    event = PaymentEvent.objects.get(id=first.record.id)
    assert event.provider == "stripe"
    assert event.currency == "usd"
    assert event.payload_hash
