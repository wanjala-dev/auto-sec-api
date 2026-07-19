from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from components.payments.domain.value_objects import (
    PaymentEventType,
    ProviderEventId,
)


@dataclass(frozen=True)
class PaymentEventEntity:
    id: UUID
    provider: str
    provider_event_id: ProviderEventId | str
    event_type: PaymentEventType | str
    status: str
    workspace_id: UUID | None = None
    method_id: UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("PaymentEventEntity.provider is required.")
        if not self.status:
            raise ValueError("PaymentEventEntity.status is required.")
        object.__setattr__(
            self,
            "provider_event_id",
            self._coerce_provider_event_id(self.provider_event_id),
        )
        object.__setattr__(
            self,
            "event_type",
            self._coerce_event_type(self.event_type),
        )

    def is_claimable(self) -> bool:
        return self.status == "received"

    @staticmethod
    def _coerce_provider_event_id(value: ProviderEventId | str) -> ProviderEventId:
        if isinstance(value, ProviderEventId):
            return value
        return ProviderEventId(value)

    @staticmethod
    def _coerce_event_type(value: PaymentEventType | str) -> PaymentEventType:
        if isinstance(value, PaymentEventType):
            return value
        return PaymentEventType(value)
