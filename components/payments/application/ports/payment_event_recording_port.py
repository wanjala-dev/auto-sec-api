from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from components.payments.domain.entities.payment_event_entity import PaymentEventEntity


@dataclass(frozen=True)
class RecordedPaymentEvent:
    record: PaymentEventEntity | None
    is_new: bool


class PaymentEventRecordingPort(Protocol):
    def record_if_new(
        self,
        *,
        provider: str,
        provider_account_id: str | None,
        provider_event_id: str,
        external_id: str | None,
        event_type: str,
        workspace_id: UUID | None,
        method_id: UUID | None,
        amount: Decimal | None,
        currency: str | None,
        payload: dict[str, Any] | None,
    ) -> RecordedPaymentEvent: ...
