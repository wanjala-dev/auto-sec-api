from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.value_objects import Money


@dataclass(frozen=True)
class PaymentDisputeEntity:
    id: UUID
    transaction_id: UUID
    provider: str
    status: str
    category: str
    amount: Decimal
    currency: str
    external_id: str
    payment_event_id: UUID | None = None
    evidence_due_by: datetime | None = None
    disputed_at: datetime | None = None
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("PaymentDisputeEntity.provider is required.")
        if not self.status:
            raise ValueError("PaymentDisputeEntity.status is required.")
        if not self.external_id:
            raise ValueError("PaymentDisputeEntity.external_id is required.")

    def money(self) -> Money:
        return Money(amount=self.amount, currency=self.currency)

    def is_resolved(self) -> bool:
        return self.status in ("won", "lost", "accepted")

    def needs_response(self) -> bool:
        return self.status in ("warning_needs_response", "needs_response")
