from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_attempt_entity import (
    PaymentAttemptEntity,
)
from components.payments.domain.value_objects import ExternalReference


def test_payment_attempt_entity_requires_positive_attempt_number():
    with pytest.raises(ValueError, match="attempt_number must be positive"):
        PaymentAttemptEntity(
            id=uuid4(),
            order_id=uuid4(),
            method_id=uuid4(),
            provider="stripe",
            attempt_number=0,
            status="created",
            idempotency_key="idem-1",
        )


def test_payment_attempt_entity_coerces_gateway_reference_and_money():
    entity = PaymentAttemptEntity(
        id=uuid4(),
        order_id=uuid4(),
        method_id=uuid4(),
        provider="stripe",
        attempt_number=1,
        status="processing",
        idempotency_key="idem-1",
        amount=Decimal("10.00"),
        currency="USD",
        gateway_reference="cs_123",
    )

    assert entity.gateway_reference == ExternalReference("cs_123")
    assert entity.money().currency == "usd"
