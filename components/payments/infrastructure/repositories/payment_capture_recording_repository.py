from __future__ import annotations

from components.payments.infrastructure.adapters.orders import (
    resolve_order_attempt_from_metadata,
)
from components.payments.infrastructure.adapters.payment_event_state import (
    mark_payment_event_processed,
)
from components.payments.application.ports.payment_capture_recording_port import (
    PaymentAttemptResolution,
    PaymentCaptureRecordingPort,
)


class PaymentCaptureRecordingRepository(PaymentCaptureRecordingPort):
    def resolve_order_attempt(self, *, metadata: dict | None, method=None) -> PaymentAttemptResolution:
        order, attempt = resolve_order_attempt_from_metadata(metadata, method=method)
        return PaymentAttemptResolution(order=order, attempt=attempt)

    def sync_gateway_reference(
        self,
        *,
        attempt,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None:
        if not attempt or not gateway_reference or getattr(attempt, "gateway_reference", None):
            return
        attempt.gateway_reference = gateway_reference
        attempt.gateway_reference_type = gateway_reference_type
        attempt.save(update_fields=["gateway_reference", "gateway_reference_type", "updated_at"])

    def mark_processed(self, *, payment_event, status: str, message: str) -> None:
        mark_payment_event_processed(payment_event, status, message)
