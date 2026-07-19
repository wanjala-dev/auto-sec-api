from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from components.payments.domain.entities.payment_dispute_entity import PaymentDisputeEntity


class PaymentDisputeStorePort(Protocol):
    def create_dispute(
        self,
        *,
        transaction_id: UUID,
        provider: str,
        status: str,
        category: str,
        amount: Decimal,
        currency: str,
        external_id: str,
        payment_event_id: UUID | None = None,
        evidence_due_by: datetime | None = None,
        disputed_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentDisputeEntity: ...

    def update_dispute_status(
        self,
        *,
        dispute_id: UUID,
        status: str,
        resolved_at: datetime | None = None,
    ) -> PaymentDisputeEntity: ...

    def find_by_external_id(self, *, provider: str, external_id: str) -> PaymentDisputeEntity | None: ...
