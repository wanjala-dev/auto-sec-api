from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.value_objects import Money


@dataclass(frozen=True)
class PaymentRefundEntity:
    id: UUID
    transaction_id: UUID
    attempt_id: UUID
    provider: str
    status: str
    reason: str
    amount: Decimal
    currency: str
    external_id: str = ""
    payment_event_id: UUID | None = None
    description: str = ""
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("PaymentRefundEntity.provider is required.")
        if not self.status:
            raise ValueError("PaymentRefundEntity.status is required.")
        if self.amount is not None and self.amount < 0:
            raise ValueError("PaymentRefundEntity.amount must be non-negative.")

    def money(self) -> Money:
        return Money(amount=self.amount, currency=self.currency)

    def is_terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "canceled")
