from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_fee_entity import PaymentFeeEntity


class TestPaymentFeeEntity:
    def test_create_valid(self):
        entity = PaymentFeeEntity(
            id=uuid4(),
            transaction_id=uuid4(),
            method_id=uuid4(),
            provider="stripe",
            context="donations",
            fee_amount=Decimal("2.90"),
            currency="usd",
            fee_percentage=Decimal("2.9000"),
            fixed_fee=Decimal("0.30"),
        )
        assert entity.fee_amount == Decimal("2.90")

    def test_negative_fee_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            PaymentFeeEntity(
                id=uuid4(),
                transaction_id=uuid4(),
                method_id=uuid4(),
                provider="stripe",
                context="shop",
                fee_amount=Decimal("-1.00"),
                currency="usd",
            )
