from __future__ import annotations

from typing import Protocol
from uuid import UUID


class PaymentEventClaimPort(Protocol):
    def claim_event(
        self,
        *,
        payment_event_id: UUID,
        claimed_by: str,
        message: str | None = None,
    ) -> bool: ...
