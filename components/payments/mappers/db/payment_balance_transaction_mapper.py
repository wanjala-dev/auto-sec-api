from __future__ import annotations

from components.payments.domain.entities.payment_balance_transaction_entity import (
    PaymentBalanceTransactionEntity,
)


def balance_txn_orm_to_entity(row) -> PaymentBalanceTransactionEntity:
    return PaymentBalanceTransactionEntity(
        id=row.id,
        workspace_id=row.workspace_id,
        transaction_type=row.transaction_type,
        source_type=row.source_type,
        source_id=row.source_id,
        amount=row.amount,
        fee=row.fee,
        net=row.net,
        currency=row.currency,
        provider=row.provider or "",
        external_id=row.external_id or "",
        available_at=row.available_at,
        description=row.description or "",
        metadata=row.metadata or {},
    )
