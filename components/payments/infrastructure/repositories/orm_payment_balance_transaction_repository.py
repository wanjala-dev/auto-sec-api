from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_balance_transaction_entity import (
    PaymentBalanceTransactionEntity,
)
from components.payments.mappers.db.payment_balance_transaction_mapper import (
    balance_txn_orm_to_entity,
)
from infrastructure.persistence.workspaces.payments.models import PaymentBalanceTransaction


class OrmPaymentBalanceTransactionRepository:
    def append(
        self,
        *,
        workspace_id: UUID,
        transaction_type: str,
        source_type: str,
        source_id: UUID,
        amount: Decimal,
        fee: Decimal,
        net: Decimal,
        currency: str,
        provider: str = "",
        external_id: str = "",
        available_at: datetime | None = None,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PaymentBalanceTransactionEntity:
        row = PaymentBalanceTransaction.objects.create(
            workspace_id=workspace_id,
            transaction_type=transaction_type,
            source_type=source_type,
            source_id=source_id,
            amount=amount,
            fee=fee,
            net=net,
            currency=currency,
            provider=provider,
            external_id=external_id,
            available_at=available_at,
            description=description,
            metadata=metadata or {},
        )
        return balance_txn_orm_to_entity(row)
