from __future__ import annotations

from components.payments.domain.entities.payment_transaction_entity import (
    PaymentTransactionEntity,
)
from infrastructure.persistence.workspaces.payments.models import PaymentTransaction


def to_payment_transaction_entity(
    transaction: PaymentTransaction,
) -> PaymentTransactionEntity:
    return PaymentTransactionEntity(
        id=transaction.id,
        attempt_id=transaction.attempt_id,
        payment_event_id=transaction.payment_event_id,
        provider=transaction.provider,
        event_type=transaction.event_type or None,
        provider_event_id=transaction.provider_event_id or None,
        external_id=transaction.external_id or None,
        status=transaction.status,
        provider_status=transaction.provider_status or None,
        amount=transaction.amount,
        currency=transaction.currency or "",
        payload=transaction.payload or {},
        occurred_at=transaction.occurred_at,
    )
