from __future__ import annotations

from components.payments.domain.entities.payment_attempt_entity import (
    PaymentAttemptEntity,
)
from infrastructure.persistence.workspaces.payments.models import PaymentAttempt


def to_payment_attempt_entity(attempt: PaymentAttempt) -> PaymentAttemptEntity:
    return PaymentAttemptEntity(
        id=attempt.id,
        order_id=attempt.order_id,
        method_id=attempt.method_id,
        provider=attempt.provider,
        attempt_number=attempt.attempt_number,
        status=attempt.status,
        idempotency_key=attempt.idempotency_key,
        amount=attempt.amount,
        currency=attempt.currency or "",
        gateway_reference=attempt.gateway_reference or None,
        gateway_reference_type=attempt.gateway_reference_type or None,
        metadata=attempt.metadata or {},
    )
