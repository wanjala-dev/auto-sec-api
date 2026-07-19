from __future__ import annotations

from uuid import UUID

from components.payments.application.ports.payment_order_store_port import PaymentOrderStorePort


class AttachProviderAttemptReferenceUseCase:
    def __init__(self, order_repository: PaymentOrderStorePort):
        self.order_repository = order_repository

    @staticmethod
    def _resolve_reference(checkout_payload: object) -> tuple[str, str]:
        if not isinstance(checkout_payload, dict):
            return "", ""
        if checkout_payload.get("provider") == "stripe" and checkout_payload.get("sessionId"):
            return checkout_payload["sessionId"], "checkout_session"
        if checkout_payload.get("provider") == "bitpay" and checkout_payload.get("invoiceId"):
            return checkout_payload["invoiceId"], "invoice"
        return "", ""

    def execute(
        self,
        *,
        order_id: UUID,
        attempt_id: UUID,
        checkout_payload: object,
    ) -> None:
        gateway_reference, gateway_reference_type = self._resolve_reference(checkout_payload)
        self.order_repository.mark_checkout_processing(
            order_id=order_id,
            attempt_id=attempt_id,
            gateway_reference=gateway_reference,
            gateway_reference_type=gateway_reference_type,
        )
