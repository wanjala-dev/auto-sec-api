from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from components.payments.domain.entities.payment_refund_entity import PaymentRefundEntity


class PaymentRefundStorePort(Protocol):
    def create_refund(
        self,
        *,
        transaction_id: UUID,
        attempt_id: UUID,
        provider: str,
        reason: str,
        amount: Decimal,
        currency: str,
        external_id: str = "",
        payment_event_id: UUID | None = None,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PaymentRefundEntity: ...

    def update_refund_status(
        self,
        *,
        refund_id: UUID,
        status: str,
        external_id: str = "",
        failure_reason: str = "",
    ) -> PaymentRefundEntity: ...

    def find_by_external_id(self, *, provider: str, external_id: str) -> PaymentRefundEntity | None: ...
