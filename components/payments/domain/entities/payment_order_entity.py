from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.value_objects import Money


@dataclass(frozen=True)
class PaymentOrderEntity:
    id: UUID
    method_id: UUID
    context: str
    status: str
    amount: Decimal | None
    currency: str
    attempt_id: UUID | None = None
    attempt_status: str | None = None
    attempt_idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.context:
            raise ValueError("PaymentOrderEntity.context is required.")
        if not self.status:
            raise ValueError("PaymentOrderEntity.status is required.")
        if not self.currency:
            raise ValueError("PaymentOrderEntity.currency is required.")

    def requires_attempt(self) -> UUID:
        if self.attempt_id is None:
            raise ValueError("PaymentOrderEntity.attempt_id is required for checkout processing.")
        return self.attempt_id

    def money(self) -> Money | None:
        if self.amount is None:
            return None
        return Money(amount=self.amount, currency=self.currency)
