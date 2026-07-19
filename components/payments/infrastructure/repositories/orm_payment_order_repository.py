from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.infrastructure.adapters.orders import create_payment_order
from components.payments.mappers.db.payment_order_mapper import to_payment_order_entity
from components.payments.application.ports.payment_flow_state_port import PaymentFlowStatePort
from components.payments.application.ports.payment_order_store_port import PaymentOrderStorePort
from infrastructure.persistence.workspaces.payments.models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentPlan,
    WorkspacePaymentMethod,
)


class OrmPaymentOrderRepository(PaymentOrderStorePort):
    """Transitional adapter backed by the legacy payment order/attempt ORM models."""

    def __init__(self, payment_flow_state: PaymentFlowStatePort | None = None):
        if payment_flow_state is None:
            from components.payments.infrastructure.repositories.orm_payment_flow_state_repository import (
                OrmPaymentFlowStateRepository,
            )

            payment_flow_state = OrmPaymentFlowStateRepository()
        self.payment_flow_state = payment_flow_state

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
    ):
        method = WorkspacePaymentMethod.objects.get(id=method_id)
        plan = PaymentPlan.objects.filter(id=plan_id).first() if plan_id else None
        order, attempt, normalized_metadata = create_payment_order(
            method=method,
            plan=plan,
            context=context,
            amount=amount,
            currency=currency,
            customer_email=customer_email,
            customer_name=customer_name,
            client_reference_id=client_reference_id,
            metadata=metadata,
        )
        return to_payment_order_entity(
            order,
            attempt=attempt,
            metadata=normalized_metadata,
        )

    def mark_checkout_failed(
        self,
        *,
        order_id: UUID,
        attempt_id: UUID,
        message: str,
    ) -> None:
        attempt = PaymentAttempt.objects.get(id=attempt_id)
        order = PaymentOrder.objects.get(id=order_id)
        self.payment_flow_state.mark_failed(
            order=order,
            attempt=attempt,
            message=message,
        )

    def mark_checkout_processing(
        self,
        *,
        order_id: UUID,
        attempt_id: UUID,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None:
        attempt = PaymentAttempt.objects.get(id=attempt_id)
        order = PaymentOrder.objects.get(id=order_id)
        self.payment_flow_state.mark_processing(
            order=order,
            attempt=attempt,
            gateway_reference=gateway_reference,
            gateway_reference_type=gateway_reference_type,
        )
