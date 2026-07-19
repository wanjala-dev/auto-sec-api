from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from components.payments.domain.entities.payment_order_entity import PaymentOrderEntity


class PaymentOrderStorePort(Protocol):
    def create_order(
        self,
        *,
        method_id: UUID,
        context: str,
        amount: Decimal | None,
        currency: str,
        customer_email: str | None,
        customer_name: str | None,
        plan_id: UUID | None,
        client_reference_id: str | None,
        metadata: dict[str, Any],
    ) -> PaymentOrderEntity: ...

    def mark_checkout_failed(
        self,
        *,
        order_id: UUID,
        attempt_id: UUID,
        message: str,
    ) -> None: ...

    def mark_checkout_processing(
        self,
        *,
        order_id: UUID,
        attempt_id: UUID,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None: ...
