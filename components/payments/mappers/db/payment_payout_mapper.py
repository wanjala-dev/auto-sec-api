from __future__ import annotations

from components.payments.domain.entities.payment_payout_entity import PaymentPayoutEntity


def payout_orm_to_entity(row) -> PaymentPayoutEntity:
    return PaymentPayoutEntity(
        id=row.id,
        workspace_id=row.workspace_id,
        method_id=row.method_id,
        provider=row.provider,
        status=row.status,
        amount=row.amount,
        currency=row.currency,
        external_id=row.external_id or "",
        failure_code=row.failure_code or "",
        failure_message=row.failure_message or "",
        arrival_date=row.arrival_date,
        metadata=row.metadata or {},
    )
