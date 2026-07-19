from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.value_objects import Money


@dataclass(frozen=True)
class PaymentPayoutEntity:
    id: UUID
    workspace_id: UUID
    method_id: UUID
    provider: str
    status: str
    amount: Decimal
    currency: str
    external_id: str
    failure_code: str = ""
    failure_message: str = ""
    arrival_date: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("PaymentPayoutEntity.provider is required.")
        if not self.status:
            raise ValueError("PaymentPayoutEntity.status is required.")

    def money(self) -> Money:
        return Money(amount=self.amount, currency=self.currency)

    def is_terminal(self) -> bool:
        return self.status in ("paid", "failed", "canceled")
