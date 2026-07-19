from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from components.payments.mappers.db.payment_order_mapper import to_payment_order_entity


def test_to_payment_order_entity_maps_attempt_and_metadata():
    order = SimpleNamespace(
        id=uuid4(),
        method_id=uuid4(),
        context="workspace_support",
        status="pending",
        amount=Decimal("10.00"),
        currency="usd",
    )
    attempt = SimpleNamespace(
        id=uuid4(),
        status="created",
        idempotency_key="attempt-key",
    )

    entity = to_payment_order_entity(
        order,
        attempt=attempt,
        metadata={"ctx": "workspace_support"},
    )

    assert entity.id == order.id
    assert entity.attempt_id == attempt.id
    assert entity.attempt_status == "created"
    assert entity.attempt_idempotency_key == "attempt-key"
    assert entity.metadata["ctx"] == "workspace_support"
