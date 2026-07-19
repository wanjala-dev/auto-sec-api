from __future__ import annotations

from uuid import UUID

from components.payments.application.ports.payment_order_store_port import PaymentOrderStorePort


class MarkCheckoutFailedUseCase:
    def __init__(self, order_repository: PaymentOrderStorePort):
        self.order_repository = order_repository

    def execute(
        self,
        *,
        order_id: UUID,
        attempt_id: UUID,
        message: str,
    ) -> None:
        self.order_repository.mark_checkout_failed(
            order_id=order_id,
            attempt_id=attempt_id,
            message=message,
        )
