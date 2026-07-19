from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from components.payments.domain.entities.payment_payout_entity import PaymentPayoutEntity


class PaymentPayoutStorePort(Protocol):
    def create_payout(
        self,
        *,
        workspace_id: UUID,
        method_id: UUID,
        provider: str,
        amount: Decimal,
        currency: str,
        external_id: str,
        arrival_date: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentPayoutEntity: ...

    def update_payout_status(
        self,
        *,
        payout_id: UUID,
        status: str,
        failure_code: str = "",
        failure_message: str = "",
    ) -> PaymentPayoutEntity: ...

    def find_by_external_id(self, *, provider: str, external_id: str) -> PaymentPayoutEntity | None: ...
