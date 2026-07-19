from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from components.payments.domain.value_objects import ExternalReference
from components.payments.mappers.db.payment_attempt_mapper import (
    to_payment_attempt_entity,
)


def test_payment_attempt_mapper_builds_domain_entity():
    attempt = SimpleNamespace(
        id=uuid4(),
        order_id=uuid4(),
        method_id=uuid4(),
        provider="stripe",
        attempt_number=2,
        status="processing",
        idempotency_key="idem-2",
        amount=Decimal("10.00"),
        currency="usd",
        gateway_reference="cs_123",
        gateway_reference_type="checkout_session",
        metadata={"ctx": "workspace_support"},
    )

    entity = to_payment_attempt_entity(attempt)

    assert entity.attempt_number == 2
    assert entity.gateway_reference == ExternalReference("cs_123")
    assert entity.metadata == {"ctx": "workspace_support"}
