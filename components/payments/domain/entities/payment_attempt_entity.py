from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.value_objects import ExternalReference, Money


@dataclass(frozen=True)
class PaymentAttemptEntity:
    id: UUID
    order_id: UUID
    method_id: UUID
    provider: str
    attempt_number: int
    status: str
    idempotency_key: str
    amount: Decimal | None = None
    currency: str = ""
    gateway_reference: ExternalReference | str | None = None
    gateway_reference_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("PaymentAttemptEntity.provider is required.")
        if self.attempt_number < 1:
            raise ValueError("PaymentAttemptEntity.attempt_number must be positive.")
        if not self.status:
            raise ValueError("PaymentAttemptEntity.status is required.")
        if not self.idempotency_key:
            raise ValueError("PaymentAttemptEntity.idempotency_key is required.")
        object.__setattr__(
            self,
            "gateway_reference",
            self._coerce_gateway_reference(self.gateway_reference),
        )

    def money(self) -> Money | None:
        if self.amount is None:
            return None
        return Money(amount=self.amount, currency=self.currency)

    @staticmethod
    def _coerce_gateway_reference(
        value: ExternalReference | str | None,
    ) -> ExternalReference | None:
        if value is None:
            return None
        if isinstance(value, ExternalReference):
            return value
        if not str(value).strip():
            return None
        return ExternalReference(value)
