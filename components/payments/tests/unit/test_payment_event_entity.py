from __future__ import annotations

from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_event_entity import PaymentEventEntity
from components.payments.domain.value_objects import (
    PaymentEventType,
    ProviderEventId,
)


def test_payment_event_entity_requires_provider():
    with pytest.raises(ValueError, match="provider is required"):
        PaymentEventEntity(
            id=uuid4(),
            provider="",
            provider_event_id="evt_123",
            event_type="checkout.session.completed",
            status="received",
        )


def test_payment_event_entity_is_claimable_only_when_received():
    entity = PaymentEventEntity(
        id=uuid4(),
        provider="stripe",
        provider_event_id="evt_123",
        event_type="checkout.session.completed",
        status="received",
    )
    processed = PaymentEventEntity(
        id=uuid4(),
        provider="stripe",
        provider_event_id="evt_456",
        event_type="checkout.session.completed",
        status="processed",
    )

    assert entity.is_claimable() is True
    assert processed.is_claimable() is False


def test_payment_event_entity_coerces_identifier_value_objects():
    entity = PaymentEventEntity(
        id=uuid4(),
        provider="stripe",
        provider_event_id="evt_123",
        event_type="checkout.session.completed",
        status="received",
    )

    assert entity.provider_event_id == ProviderEventId("evt_123")
    assert entity.event_type == PaymentEventType("checkout.session.completed")
