from __future__ import annotations

from components.payments.domain.entities.payment_dispute_entity import PaymentDisputeEntity


def dispute_orm_to_entity(row) -> PaymentDisputeEntity:
    return PaymentDisputeEntity(
        id=row.id,
        transaction_id=row.transaction_id,
        provider=row.provider,
        status=row.status,
        category=row.category,
        amount=row.amount,
        currency=row.currency,
        external_id=row.external_id or "",
        payment_event_id=row.payment_event_id,
        evidence_due_by=row.evidence_due_by,
        disputed_at=row.disputed_at,
        resolved_at=row.resolved_at,
        metadata=row.metadata or {},
    )
