from __future__ import annotations

from components.payments.domain.entities.payment_refund_entity import PaymentRefundEntity


def refund_orm_to_entity(row) -> PaymentRefundEntity:
    return PaymentRefundEntity(
        id=row.id,
        transaction_id=row.transaction_id,
        attempt_id=row.attempt_id,
        provider=row.provider,
        status=row.status,
        reason=row.reason,
        amount=row.amount,
        currency=row.currency,
        external_id=row.external_id or "",
        payment_event_id=row.payment_event_id,
        description=row.description or "",
        failure_reason=row.failure_reason or "",
        metadata=row.metadata or {},
        completed_at=row.completed_at,
    )
