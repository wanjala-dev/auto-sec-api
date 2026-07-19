from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from components.payments.domain.entities.payment_transaction_entity import (
    PaymentTransactionEntity,
)
from components.payments.domain.value_objects import (
    ExternalReference,
    PaymentEventType,
    ProviderEventId,
)


def test_payment_transaction_entity_coerces_identifier_value_objects():
    entity = PaymentTransactionEntity(
        id=uuid4(),
        attempt_id=uuid4(),
        provider="stripe",
        status="succeeded",
        event_type="checkout.session.completed",
        provider_event_id="evt_123",
        external_id="cs_123",
        amount=Decimal("20.00"),
        currency="USD",
    )

    assert entity.event_type == PaymentEventType("checkout.session.completed")
    assert entity.provider_event_id == ProviderEventId("evt_123")
    assert entity.external_id == ExternalReference("cs_123")
    assert entity.money().currency == "usd"
