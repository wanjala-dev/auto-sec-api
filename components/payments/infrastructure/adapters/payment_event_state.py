from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

if TYPE_CHECKING:
    from infrastructure.persistence.workspaces.payments.models import PaymentEvent

logger = logging.getLogger(__name__)

# Event types that represent a successful payment worth notifying about.
_SUCCESS_EVENT_TYPES = frozenset({
    "checkout.session.completed",
    "invoice.payment_succeeded",
    "invoice_payment.paid",
    "charge.succeeded",
})


def _publish_payment_succeeded(payment_event: PaymentEvent) -> None:
    """Extract metadata from the payment event and publish PaymentSucceeded.

    Runs inside ``transaction.on_commit`` so the domain event is only
    published after the DB row is committed.  Each subscriber runs as
    a separate Celery task — fault-isolated and independently retryable.
    """
    from django.db import transaction as db_transaction

    def _emit():
        try:
            from components.payments.domain.events import PaymentSucceeded
            from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
                CeleryEventPublisher,
            )

            payload = payment_event.payload or {}
            obj = payload.get("data", {}).get("object", {})
            metadata = dict(obj.get("metadata", {}) or {})

            # For invoice events, the checkout context lives in
            # subscription_details.metadata (Stripe propagates checkout
            # metadata to the subscription, not the invoice itself).
            if not metadata.get("context"):
                sub_details = obj.get("subscription_details") or {}
                sub_metadata = sub_details.get("metadata") if isinstance(sub_details, dict) else {}
                if sub_metadata and isinstance(sub_metadata, dict) and sub_metadata.get("context"):
                    metadata = {**metadata, **sub_metadata}

            # For invoice renewals, metadata is on the line items
            # (Stripe propagates checkout metadata to line items).
            if not metadata.get("context"):
                lines = obj.get("lines", {}).get("data", [])
                if lines and isinstance(lines[0], dict):
                    line_meta = lines[0].get("metadata", {})
                    if line_meta and isinstance(line_meta, dict) and line_meta.get("context"):
                        metadata = {**metadata, **line_meta}

            # Fall back to invoice-level customer fields for payer info
            if not metadata.get("email"):
                metadata["email"] = obj.get("customer_email", "") or ""
            if not metadata.get("name"):
                metadata["name"] = obj.get("customer_name", "") or ""

            if not metadata.get("context"):
                return

            # The Connect application fee Stripe actually took, in MINOR units
            # (cents). It sits at the top level of charge.succeeded and
            # invoice.payment_succeeded payloads. The one-time
            # checkout.session.completed payload does NOT carry it (it lives on
            # the charge, which the session doesn't expand) — there it stays
            # "0" and the revenue-share fee handler fetches the real value from
            # Stripe. We read it but never recompute it: record what Stripe took.
            raw_fee = obj.get("application_fee_amount")
            application_fee_amount = "0" if raw_fee in (None, "") else str(raw_fee)

            event = PaymentSucceeded(
                payment_event_id=payment_event.id,
                workspace_id=metadata.get("workspace_id", ""),
                provider=payment_event.provider or "",
                event_type=payment_event.event_type or "",
                context=metadata.get("context", ""),
                amount=str(payment_event.amount or "0"),
                currency=payment_event.currency or metadata.get("currency", "USD"),
                application_fee_amount=application_fee_amount,
                payer_name=metadata.get("name", ""),
                payer_email=metadata.get("email", "") or metadata.get("donor_email", ""),
                recipient_id=metadata.get("recipient_id", ""),
                recipient_name=metadata.get("recipient_name", ""),
                project_id=metadata.get("project_id", ""),
                campaign_id=metadata.get("campaign_id", ""),
                event_id=metadata.get("event_id", ""),
                metadata=metadata,
            )
            CeleryEventPublisher().publish(event)
            logger.info(
                "Published PaymentSucceeded for %s context=%s amount=%s",
                payment_event.id,
                event.context,
                event.amount,
            )
        except Exception:
            logger.exception(
                "Failed to publish PaymentSucceeded for %s (non-fatal)",
                payment_event.id,
            )

    db_transaction.on_commit(_emit)


def mark_payment_event_processed(
    payment_event: PaymentEvent | None,
    status: str,
    message: str | None = None,
) -> bool:
    """Atomically mark a payment event as processed.

    Uses an atomic UPDATE with a status filter so that two concurrent callers
    cannot both "win" — the second caller sees ``updated == 0`` and returns
    ``False`` instead of silently overwriting the first caller's status.

    Returns ``True`` if the update was applied, ``False`` if the event was
    already in a terminal state (processed/ignored/failed) or was ``None``.
    """
    if payment_event is None:
        return False

    now = timezone.now()
    # Only transition from non-terminal states.
    updated = (
        type(payment_event)
        .objects.filter(id=payment_event.id)
        .exclude(status__in=[payment_event.STATUS_PROCESSED, payment_event.STATUS_IGNORED, payment_event.STATUS_FAILED])
        .update(
            status=status,
            status_message=message or payment_event.status_message or "",
            processed_at=now,
            updated_at=now,
        )
    )
    if updated:
        payment_event.status = status
        if message:
            payment_event.status_message = message
        payment_event.processed_at = now
        payment_event.updated_at = now

        # Fan out to domain event handlers for successful payments.
        if (
            status == "processed"
            and (payment_event.event_type or "") in _SUCCESS_EVENT_TYPES
        ):
            _publish_payment_succeeded(payment_event)

    return bool(updated)


def mark_payment_event_processing(
    payment_event: PaymentEvent | None,
    message: str | None = None,
) -> bool:
    """Atomically mark a payment event as processing.

    Uses a filtered UPDATE so two concurrent webhook deliveries cannot
    both claim the same event.  Returns True if the claim succeeded.
    """
    if payment_event is None:
        return False

    now = timezone.now()
    updated = (
        type(payment_event)
        .objects.filter(id=payment_event.id)
        .exclude(
            status__in=[
                payment_event.STATUS_PROCESSED,
                payment_event.STATUS_IGNORED,
                payment_event.STATUS_FAILED,
            ]
        )
        .update(
            status=payment_event.STATUS_PROCESSING,
            status_message=message or payment_event.status_message or "",
            processing_at=now,
            processed_at=None,
            updated_at=now,
        )
    )
    if updated:
        payment_event.status = payment_event.STATUS_PROCESSING
        if message:
            payment_event.status_message = message
        payment_event.processing_at = now
        payment_event.processed_at = None
        payment_event.updated_at = now
    return bool(updated)


def payment_event_is_processable_for_worker(payment_event: PaymentEvent) -> bool:
    if payment_event.status in {payment_event.STATUS_PROCESSED, payment_event.STATUS_IGNORED}:
        return False
    return True


def claim_payment_event_processing(
    payment_event: PaymentEvent | None,
    message: str | None = None,
) -> bool:
    if payment_event is None:
        return False

    now = timezone.now()
    stale_before = now - timedelta(minutes=15)
    filters = (
        Q(status__in=[payment_event.STATUS_RECEIVED, payment_event.STATUS_FAILED])
        | Q(status=payment_event.STATUS_PROCESSING, processing_at__isnull=True)
        | Q(status=payment_event.STATUS_PROCESSING, processing_at__lte=stale_before)
    )
    updated = (
        type(payment_event)
        .objects.filter(id=payment_event.id)
        .filter(filters)
        .update(
            status=payment_event.STATUS_PROCESSING,
            status_message=(message or payment_event.status_message or ""),
            processing_at=now,
            processed_at=None,
            updated_at=now,
        )
    )
    if updated:
        payment_event.status = payment_event.STATUS_PROCESSING
        if message:
            payment_event.status_message = message
        payment_event.processing_at = now
        payment_event.processed_at = None
        payment_event.updated_at = now
        return True
    return False
