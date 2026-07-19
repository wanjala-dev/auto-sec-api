from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_order_entity import PaymentOrderEntity
from components.payments.application.ports.payment_order_store_port import PaymentOrderStorePort


class CreatePaymentOrderUseCase:
    def __init__(self, order_repository: PaymentOrderStorePort):
        self.order_repository = order_repository

    def execute(
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
    ) -> PaymentOrderEntity:
        return self.order_repository.create_order(
            method_id=method_id,
            context=context,
            amount=amount,
            currency=currency,
            customer_email=customer_email,
            customer_name=customer_name,
            plan_id=plan_id,
            client_reference_id=client_reference_id,
            metadata=metadata,
        )
