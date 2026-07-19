from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PaymentAttemptResolution:
    order: Any | None
    attempt: Any | None


class PaymentCaptureRecordingPort(Protocol):
    def resolve_order_attempt(self, *, metadata: dict | None, method: Any | None = None) -> PaymentAttemptResolution: ...

    def sync_gateway_reference(
        self,
        *,
        attempt: Any | None,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None: ...

    def mark_processed(self, *, payment_event: Any | None, status: str, message: str) -> None: ...
