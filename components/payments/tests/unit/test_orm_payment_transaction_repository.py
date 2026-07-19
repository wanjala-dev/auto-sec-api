from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from components.payments.domain.entities.payment_transaction_entity import (
    PaymentTransactionEntity,
)
from components.payments.infrastructure.repositories.orm_payment_transaction_repository import (
    OrmPaymentTransactionRepository,
)


def test_orm_payment_transaction_repository_maps_created_transaction(monkeypatch):
    repository = OrmPaymentTransactionRepository()
    transaction_id = uuid4()
    attempt_id = uuid4()

    def fake_record_payment_transaction(**kwargs):
        return SimpleNamespace(
            id=transaction_id,
            attempt_id=attempt_id,
            payment_event_id=None,
            provider=kwargs["provider"],
            event_type=kwargs["event_type"],
            provider_event_id="evt_123",
            external_id=kwargs["external_id"],
            status=kwargs["status"],
            provider_status=kwargs["provider_status"],
            amount=kwargs["amount"],
            currency=kwargs["currency"],
            payload=kwargs["payload"],
            occurred_at=None,
        )

    monkeypatch.setattr(
        "components.payments.infrastructure.repositories.orm_payment_transaction_repository.record_payment_transaction",
        fake_record_payment_transaction,
    )

    transaction = repository.record_transaction(
        order="order",
        attempt="attempt",
        provider="stripe",
        status="succeeded",
        event_type="checkout.session.completed",
        external_id="cs_123",
        provider_status="paid",
        amount=Decimal("10.00"),
        currency="usd",
        payload={"id": "evt_123"},
    )

    assert isinstance(transaction, PaymentTransactionEntity)
    assert transaction.id == transaction_id
    assert transaction.attempt_id == attempt_id
    assert transaction.provider == "stripe"
