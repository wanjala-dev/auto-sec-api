from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.value_objects import (
    ExternalReference,
    Money,
    PaymentEventType,
    ProviderEventId,
)


@dataclass(frozen=True)
class PaymentTransactionEntity:
    id: UUID
    attempt_id: UUID
    provider: str
    status: str
    payment_event_id: UUID | None = None
    event_type: PaymentEventType | str | None = None
    provider_event_id: ProviderEventId | str | None = None
    external_id: ExternalReference | str | None = None
    provider_status: str | None = None
    amount: Decimal | None = None
    currency: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("PaymentTransactionEntity.provider is required.")
        if not self.status:
            raise ValueError("PaymentTransactionEntity.status is required.")
        object.__setattr__(self, "event_type", self._coerce_event_type(self.event_type))
        object.__setattr__(
            self,
            "provider_event_id",
            self._coerce_provider_event_id(self.provider_event_id),
        )
        object.__setattr__(self, "external_id", self._coerce_external_id(self.external_id))

    def money(self) -> Money | None:
        if self.amount is None:
            return None
        return Money(amount=self.amount, currency=self.currency)

    @staticmethod
    def _coerce_event_type(
        value: PaymentEventType | str | None,
    ) -> PaymentEventType | None:
        if value is None:
            return None
        if isinstance(value, PaymentEventType):
            return value
        if not str(value).strip():
            return None
        return PaymentEventType(value)

    @staticmethod
    def _coerce_provider_event_id(
        value: ProviderEventId | str | None,
    ) -> ProviderEventId | None:
        if value is None:
            return None
        if isinstance(value, ProviderEventId):
            return value
        if not str(value).strip():
            return None
        return ProviderEventId(value)

    @staticmethod
    def _coerce_external_id(
        value: ExternalReference | str | None,
    ) -> ExternalReference | None:
        if value is None:
            return None
        if isinstance(value, ExternalReference):
            return value
        if not str(value).strip():
            return None
        return ExternalReference(value)
