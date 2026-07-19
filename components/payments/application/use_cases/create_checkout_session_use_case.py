from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.application.use_cases.attach_provider_attempt_reference_use_case import (
    AttachProviderAttemptReferenceUseCase,
)
from components.payments.application.use_cases.create_payment_order_use_case import (
    CreatePaymentOrderUseCase,
)
from components.payments.application.use_cases.mark_checkout_failed_use_case import (
    MarkCheckoutFailedUseCase,
)


@dataclass(frozen=True)
class CheckoutCreationResult:
    order_id: UUID
    attempt_id: UUID
    checkout_payload: object
    metadata: dict[str, Any]


class CreateCheckoutSessionUseCase:
    """Create the internal payment order and provider checkout session."""

    def __init__(
        self,
        create_payment_order: CreatePaymentOrderUseCase,
        mark_checkout_failed: MarkCheckoutFailedUseCase,
        attach_provider_attempt_reference: AttachProviderAttemptReferenceUseCase,
    ):
        self.create_payment_order = create_payment_order
        self.mark_checkout_failed = mark_checkout_failed
        self.attach_provider_attempt_reference = attach_provider_attempt_reference

    def execute(
        self,
        *,
        gateway,
        method,
        plan,
        context: str,
        amount: Decimal | None,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None,
        customer_id: str | None,
        client_reference_id: str | None,
        metadata: dict[str, Any] | None,
        customer_name: str | None,
        donor_tip=None,
    ) -> CheckoutCreationResult:
        order_record = self.create_payment_order.execute(
            method_id=method.id,
            context=context,
            amount=amount,
            currency=currency,
            customer_email=customer_email,
            customer_name=customer_name,
            plan_id=getattr(plan, "id", None),
            client_reference_id=client_reference_id,
            metadata=metadata or {},
        )
        try:
            checkout_payload = gateway.create_checkout_session(
                method,
                plan,
                amount=amount,
                currency=currency,
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=customer_email,
                customer_id=customer_id,
                client_reference_id=client_reference_id,
                metadata=order_record.metadata,
                idempotency_key=order_record.attempt_idempotency_key,
                donor_tip=donor_tip,
            )
        except Exception as exc:
            self.mark_checkout_failed.execute(
                order_id=order_record.id,
                attempt_id=order_record.requires_attempt(),
                message=str(exc),
            )
            raise

        self.attach_provider_attempt_reference.execute(
            order_id=order_record.id,
            attempt_id=order_record.requires_attempt(),
            checkout_payload=checkout_payload,
        )
        return CheckoutCreationResult(
            order_id=order_record.id,
            attempt_id=order_record.requires_attempt(),
            checkout_payload=checkout_payload,
            metadata=order_record.metadata,
        )
