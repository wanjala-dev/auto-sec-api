from __future__ import annotations

from components.payments.domain.entities.payment_order_entity import PaymentOrderEntity
from infrastructure.persistence.workspaces.payments.models import PaymentAttempt, PaymentOrder


def to_payment_order_entity(
    order: PaymentOrder,
    *,
    attempt: PaymentAttempt | None = None,
    metadata: dict | None = None,
) -> PaymentOrderEntity:
    # PaymentOrder doesn't carry a direct ``method`` FK — the connection
    # to a payment method goes through the related ``plan`` (which always
    # belongs to exactly one ``WorkspacePaymentMethod``). The workspace
    # checkout flow also stamps ``method_id`` into ``order.metadata`` as a
    # backup for orders that have no plan (custom-amount one-offs). Older
    # tests pass a SimpleNamespace mock without ``plan_id``, so guard with
    # getattr on every hop.
    plan = getattr(order, "plan", None)
    method_id = getattr(plan, "method_id", None) if plan is not None else None
    if method_id is None:
        method_id = (getattr(order, "metadata", None) or {}).get("method_id")
    if method_id is None:
        method_id = getattr(order, "method_id", None)
    return PaymentOrderEntity(
        id=order.id,
        method_id=method_id,
        context=order.context,
        status=order.status,
        amount=order.amount,
        currency=order.currency,
        attempt_id=getattr(attempt, "id", None),
        attempt_status=getattr(attempt, "status", None),
        attempt_idempotency_key=getattr(attempt, "idempotency_key", None),
        metadata=metadata or {},
    )
