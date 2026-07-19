from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_refund_entity import PaymentRefundEntity


class TestPaymentRefundEntity:
    def test_create_valid(self):
        entity = PaymentRefundEntity(
            id=uuid4(),
            transaction_id=uuid4(),
            attempt_id=uuid4(),
            provider="stripe",
            status="pending",
            reason="requested_by_customer",
            amount=Decimal("10.00"),
            currency="usd",
        )
        assert entity.provider == "stripe"
        assert entity.money().amount == Decimal("10.00")
        assert not entity.is_terminal()

    def test_terminal_statuses(self):
        for s in ("succeeded", "failed", "canceled"):
            entity = PaymentRefundEntity(
                id=uuid4(),
                transaction_id=uuid4(),
                attempt_id=uuid4(),
                provider="stripe",
                status=s,
                reason="other",
                amount=Decimal("5.00"),
                currency="usd",
            )
            assert entity.is_terminal()

    def test_provider_required(self):
        with pytest.raises(ValueError, match="provider"):
            PaymentRefundEntity(
                id=uuid4(),
                transaction_id=uuid4(),
                attempt_id=uuid4(),
                provider="",
                status="pending",
                reason="other",
                amount=Decimal("5.00"),
                currency="usd",
            )

    def test_negative_amount_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            PaymentRefundEntity(
                id=uuid4(),
                transaction_id=uuid4(),
                attempt_id=uuid4(),
                provider="stripe",
                status="pending",
                reason="other",
                amount=Decimal("-1.00"),
                currency="usd",
            )
