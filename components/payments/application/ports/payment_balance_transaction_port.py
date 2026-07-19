from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from components.payments.domain.entities.payment_balance_transaction_entity import (
    PaymentBalanceTransactionEntity,
)


class PaymentBalanceTransactionPort(Protocol):
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
    ) -> PaymentBalanceTransactionEntity: ...
