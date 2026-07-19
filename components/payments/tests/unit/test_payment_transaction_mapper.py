from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from components.payments.domain.value_objects import (
    ExternalReference,
    PaymentEventType,
    ProviderEventId,
)
from components.payments.mappers.db.payment_transaction_mapper import (
    to_payment_transaction_entity,
)


def test_payment_transaction_mapper_builds_domain_entity():
    transaction = SimpleNamespace(
        id=uuid4(),
        attempt_id=uuid4(),
        payment_event_id=uuid4(),
        provider="stripe",
        event_type="checkout.session.completed",
        provider_event_id="evt_123",
        external_id="cs_123",
        status="succeeded",
        provider_status="paid",
        amount=Decimal("10.00"),
        currency="usd",
        payload={"id": "evt_123"},
        occurred_at=datetime(2026, 3, 27, 12, 0, 0),
    )

    entity = to_payment_transaction_entity(transaction)

    assert entity.event_type == PaymentEventType("checkout.session.completed")
    assert entity.provider_event_id == ProviderEventId("evt_123")
    assert entity.external_id == ExternalReference("cs_123")
    assert entity.payload == {"id": "evt_123"}
