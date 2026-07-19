from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol


class PaymentTransactionStorePort(Protocol):
    def record_transaction(
        self,
        *,
        order: Any | None,
        attempt: Any | None,
        provider: str,
        status: str,
        payment_event: Any | None = None,
        event_type: str | None = None,
        external_id: str | None = None,
        provider_status: str | None = None,
        amount: Decimal | None = None,
        currency: str | None = None,
        payload: dict | None = None,
        update_statuses: bool = True,
    ) -> Any: ...
