from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from components.payments.domain.entities.payment_dispute_entity import PaymentDisputeEntity


class TestPaymentDisputeEntity:
    def test_create_valid(self):
        entity = PaymentDisputeEntity(
            id=uuid4(),
            transaction_id=uuid4(),
            provider="stripe",
            status="needs_response",
            category="fraudulent",
            amount=Decimal("100.00"),
            currency="usd",
            external_id="dp_123",
        )
        assert entity.needs_response()
        assert not entity.is_resolved()

    def test_resolved_statuses(self):
        for s in ("won", "lost", "accepted"):
            entity = PaymentDisputeEntity(
                id=uuid4(),
                transaction_id=uuid4(),
                provider="stripe",
                status=s,
                category="general",
                amount=Decimal("50.00"),
                currency="usd",
                external_id="dp_456",
            )
            assert entity.is_resolved()

    def test_external_id_required(self):
        with pytest.raises(ValueError, match="external_id"):
            PaymentDisputeEntity(
                id=uuid4(),
                transaction_id=uuid4(),
                provider="stripe",
                status="needs_response",
                category="general",
                amount=Decimal("50.00"),
                currency="usd",
                external_id="",
            )
