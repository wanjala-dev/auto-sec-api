from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class PaymentBalanceTransactionEntity:
    id: UUID
    workspace_id: UUID
    transaction_type: str
    source_type: str
    source_id: UUID
    amount: Decimal
    fee: Decimal
    net: Decimal
    currency: str
    provider: str = ""
    external_id: str = ""
    available_at: datetime | None = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.transaction_type:
            raise ValueError("PaymentBalanceTransactionEntity.transaction_type is required.")
        if not self.source_type:
            raise ValueError("PaymentBalanceTransactionEntity.source_type is required.")
        if not self.currency:
            raise ValueError("PaymentBalanceTransactionEntity.currency is required.")
