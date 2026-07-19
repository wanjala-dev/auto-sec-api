from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_order_entity import PaymentOrderEntity
from components.payments.domain.value_objects import Money


def test_payment_order_entity_requires_currency():
    with pytest.raises(ValueError, match="currency is required"):
        PaymentOrderEntity(
            id=uuid4(),
            method_id=uuid4(),
            context="workspace_support",
            status="pending",
            amount=Decimal("10.00"),
            currency="",
        )


def test_payment_order_entity_requires_attempt_for_checkout_processing():
    entity = PaymentOrderEntity(
        id=uuid4(),
        method_id=uuid4(),
        context="workspace_support",
        status="pending",
        amount=Decimal("10.00"),
        currency="usd",
    )

    with pytest.raises(ValueError, match="attempt_id is required"):
        entity.requires_attempt()


def test_payment_order_entity_exposes_money_value_object():
    entity = PaymentOrderEntity(
        id=uuid4(),
        method_id=uuid4(),
        context="workspace_support",
        status="pending",
        amount=Decimal("10.00"),
        currency="USD",
    )

    assert entity.money() == Money(amount=Decimal("10.00"), currency="usd")
