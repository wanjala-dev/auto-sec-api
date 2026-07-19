from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from django.utils import timezone

from infrastructure.persistence.workspaces.payments.models import (
    PaymentAttempt,
    PaymentEvent,
    PaymentOrder,
    PaymentPlan,
    PaymentTransaction,
    WorkspacePaymentMethod,
)


def _mark_payment_order_status(
    order: PaymentOrder | None,
    status: str,
    message: str | None = None,
) -> None:
    if order is None:
        return

    order.status = status
    update_fields = ["status", "updated_at"]
    if message is not None:
        order.status_message = message
        update_fields.append("status_message")
    if status in {
        PaymentOrder.STATUS_SUCCEEDED,
        PaymentOrder.STATUS_FAILED,
        PaymentOrder.STATUS_CANCELED,
    }:
        order.completed_at = timezone.now()
        update_fields.append("completed_at")
    order.save(update_fields=update_fields)


def _mark_payment_attempt_status(
    attempt: PaymentAttempt | None,
    status: str,
    message: str | None = None,
    *,
    gateway_reference: str | None = None,
    gateway_reference_type: str | None = None,
) -> None:
    if attempt is None:
        return

    attempt.status = status
    update_fields = ["status", "updated_at"]
    if message is not None:
        attempt.status_message = message
        update_fields.append("status_message")
    if gateway_reference:
        attempt.gateway_reference = gateway_reference
        attempt.gateway_reference_type = gateway_reference_type or ""
        update_fields.extend(["gateway_reference", "gateway_reference_type"])
    if status in {
        PaymentAttempt.STATUS_SUCCEEDED,
        PaymentAttempt.STATUS_FAILED,
        PaymentAttempt.STATUS_CANCELED,
    }:
        attempt.completed_at = timezone.now()
        update_fields.append("completed_at")
    attempt.save(update_fields=update_fields)


def create_payment_order(
    *,
    method: WorkspacePaymentMethod,
    context: str,
    plan: PaymentPlan | None = None,
    amount: Decimal | None = None,
    currency: str | None = None,
    customer_email: str | None = None,
    customer_name: str | None = None,
    client_reference_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[PaymentOrder, PaymentAttempt, dict[str, Any]]:
    """Create an internal order and initial attempt, returning gateway-ready metadata."""
    order_amount = amount if amount is not None else (plan.amount if plan else None)
    currency_value = (currency or (plan.currency if plan else "usd") or "usd").lower()

    order = PaymentOrder.objects.create(
        workspace=method.workspace,
        plan=plan,
        context=context,
        status=PaymentOrder.STATUS_PENDING,
        amount=order_amount,
        currency=currency_value,
        customer_email=customer_email or "",
        customer_name=customer_name or "",
        client_reference_id=client_reference_id or "",
        idempotency_key=uuid.uuid4().hex,
        metadata=metadata or {},
    )

    attempt_number = order.attempts.count() + 1
    attempt = PaymentAttempt.objects.create(
        order=order,
        method=method,
        provider=method.provider.slug,
        attempt_number=attempt_number,
        status=PaymentAttempt.STATUS_CREATED,
        amount=order_amount,
        currency=currency_value,
        idempotency_key=uuid.uuid4().hex,
        metadata=metadata or {},
    )

    payload = (metadata or {}).copy()
    payload.setdefault("order_id", str(order.id))
    payload.setdefault("attempt_id", str(attempt.id))
    payload.setdefault("method_id", str(method.id))
    payload.setdefault("workspace_id", str(method.workspace_id))
    payload.setdefault("context", context)
    if plan:
        payload.setdefault("plan_id", str(plan.id))

    if payload != (metadata or {}):
        order.metadata = payload
        attempt.metadata = payload
        order.save(update_fields=["metadata", "updated_at"])
        attempt.save(update_fields=["metadata", "updated_at"])

    return order, attempt, payload


def resolve_order_attempt_from_metadata(
    metadata: dict[str, Any] | None,
    *,
    method: WorkspacePaymentMethod | None = None,
) -> tuple[PaymentOrder | None, PaymentAttempt | None]:
    """Locate the order/attempt references from provider metadata."""
    if not metadata:
        return None, None

    order_id = metadata.get("order_id")
    attempt_id = metadata.get("attempt_id")

    attempt = None
    order = None

    if attempt_id:
        try:
            attempt = (
                PaymentAttempt.objects.select_related("order")
                .filter(id=attempt_id)
                .first()
            )
        except (TypeError, ValueError):
            attempt = None
        if attempt:
            order = attempt.order

    if not order and order_id:
        try:
            order = PaymentOrder.objects.filter(id=order_id).first()
        except (TypeError, ValueError):
            order = None

    if order and not attempt and method:
        attempt = (
            order.attempts.filter(method=method)
            .order_by("-created_at")
            .first()
        )

    return order, attempt


def record_payment_transaction(
    *,
    order: PaymentOrder | None,
    attempt: PaymentAttempt | None,
    provider: str,
    status: str,
    payment_event: PaymentEvent | None = None,
    event_type: str | None = None,
    external_id: str | None = None,
    provider_status: str | None = None,
    amount: Decimal | None = None,
    currency: str | None = None,
    payload: dict[str, Any] | None = None,
    update_statuses: bool = True,
) -> PaymentTransaction | None:
    """Persist a gateway transaction and update order/attempt status when applicable."""
    if not attempt:
        return None

    payload_value: dict[str, Any] = {}
    if isinstance(payload, dict) and payload:
        try:
            payload_value = json.loads(json.dumps(payload, default=str))
        except (TypeError, ValueError):
            payload_value = {}

    provider_event_id = ""
    if payment_event and payment_event.event_id:
        provider_event_id = payment_event.event_id
    elif payload and isinstance(payload, dict):
        provider_event_id = payload.get("id", "") or payload.get("token", "") or ""

    existing = None
    if payment_event:
        existing = PaymentTransaction.objects.filter(
            payment_event=payment_event,
            attempt=attempt,
        ).first()
    if not existing and provider_event_id:
        existing = PaymentTransaction.objects.filter(
            provider=provider,
            provider_event_id=provider_event_id,
            attempt=attempt,
        ).first()
    if not existing and external_id and event_type:
        existing = PaymentTransaction.objects.filter(
            provider=provider,
            external_id=external_id,
            event_type=event_type,
            attempt=attempt,
        ).first()
    if existing:
        return existing

    transaction = PaymentTransaction.objects.create(
        attempt=attempt,
        payment_event=payment_event,
        provider=provider,
        event_type=event_type or "",
        provider_event_id=provider_event_id,
        external_id=external_id or "",
        status=status,
        provider_status=provider_status or "",
        amount=amount,
        currency=(currency or "").lower(),
        payload=payload_value,
        occurred_at=timezone.now(),
    )

    currency_value = (currency or "").lower()
    if amount is not None:
        attempt_updates = []
        if attempt.amount != amount:
            attempt.amount = amount
            attempt_updates.append("amount")
        if currency_value and attempt.currency != currency_value:
            attempt.currency = currency_value
            attempt_updates.append("currency")
        if attempt_updates:
            attempt.save(update_fields=attempt_updates + ["updated_at"])

        if order:
            order_updates = []
            if order.amount != amount:
                order.amount = amount
                order_updates.append("amount")
            if currency_value and order.currency != currency_value:
                order.currency = currency_value
                order_updates.append("currency")
            if order_updates:
                order.save(update_fields=order_updates + ["updated_at"])

    if update_statuses:
        if status == PaymentTransaction.STATUS_SUCCEEDED:
            _mark_payment_attempt_status(attempt, PaymentAttempt.STATUS_SUCCEEDED)
            if order:
                _mark_payment_order_status(order, PaymentOrder.STATUS_SUCCEEDED)
        elif status == PaymentTransaction.STATUS_FAILED:
            _mark_payment_attempt_status(attempt, PaymentAttempt.STATUS_FAILED)

    return transaction
