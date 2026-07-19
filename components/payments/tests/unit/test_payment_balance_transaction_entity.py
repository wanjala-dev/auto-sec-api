from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_balance_transaction_entity import (
    PaymentBalanceTransactionEntity,
)


class TestPaymentBalanceTransactionEntity:
    def test_create_valid(self):
        entity = PaymentBalanceTransactionEntity(
            id=uuid4(),
            workspace_id=uuid4(),
            transaction_type="payment",
            source_type="PaymentTransaction",
            source_id=uuid4(),
            amount=Decimal("100.00"),
            fee=Decimal("2.90"),
            net=Decimal("97.10"),
            currency="usd",
        )
        assert entity.net == Decimal("97.10")

    def test_transaction_type_required(self):
        with pytest.raises(ValueError, match="transaction_type"):
            PaymentBalanceTransactionEntity(
                id=uuid4(),
                workspace_id=uuid4(),
                transaction_type="",
                source_type="PaymentTransaction",
                source_id=uuid4(),
                amount=Decimal("10.00"),
                fee=Decimal("0"),
                net=Decimal("10.00"),
                currency="usd",
            )

    def test_currency_required(self):
        with pytest.raises(ValueError, match="currency"):
            PaymentBalanceTransactionEntity(
                id=uuid4(),
                workspace_id=uuid4(),
                transaction_type="refund",
                source_type="PaymentRefund",
                source_id=uuid4(),
                amount=Decimal("-10.00"),
                fee=Decimal("0"),
                net=Decimal("-10.00"),
                currency="",
            )
