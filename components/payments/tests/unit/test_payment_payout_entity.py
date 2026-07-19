from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_payout_entity import PaymentPayoutEntity


class TestPaymentPayoutEntity:
    def test_create_valid(self):
        entity = PaymentPayoutEntity(
            id=uuid4(),
            workspace_id=uuid4(),
            method_id=uuid4(),
            provider="stripe",
            status="pending",
            amount=Decimal("500.00"),
            currency="usd",
            external_id="po_123",
        )
        assert not entity.is_terminal()
        assert entity.money().amount == Decimal("500.00")

    def test_terminal_statuses(self):
        for s in ("paid", "failed", "canceled"):
            entity = PaymentPayoutEntity(
                id=uuid4(),
                workspace_id=uuid4(),
                method_id=uuid4(),
                provider="stripe",
                status=s,
                amount=Decimal("100.00"),
                currency="usd",
                external_id="po_456",
            )
            assert entity.is_terminal()

    def test_provider_required(self):
        with pytest.raises(ValueError, match="provider"):
            PaymentPayoutEntity(
                id=uuid4(),
                workspace_id=uuid4(),
                method_id=uuid4(),
                provider="",
                status="pending",
                amount=Decimal("100.00"),
                currency="usd",
                external_id="po_789",
            )
