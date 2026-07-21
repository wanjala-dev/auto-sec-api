"""Web-push delivery task (T1-S6 — the real sender).

The dispatch funnel records pending ``NotificationDelivery`` rows and
enqueues this task. The task claims each deliverable ledger row (pending
or failed — the claim increments ``attempts``), builds one payload for the
notification, and transmits it per device through the
``WebPushSenderPort`` (pywebpush adapter behind the provider).

Outcomes per row:

    sent               push service accepted the message
    skipped            flag/keys off, notification row gone, device not
                       active, or the push service reported the
                       subscription gone (404/410 — device also expired
                       in the registry). Terminal, never retried.
    failed             transient push-service/network error — the task
                       re-raises for Celery retry; the retry re-claims
                       failed rows via ``deliverable_for`` (sent/skipped
                       rows are excluded, so re-runs are idempotent).

Flag OFF (``WEB_PUSH_ENABLED`` false, or no VAPID private key) stays a
truthful no-op: pending rows transition to ``skipped`` with an explicit
reason — the ledger never claims a send that didn't happen.

Payloads may carry user content (title/body) — log ids and counts only,
never the payload.
"""

from __future__ import annotations

import json
import logging

from celery import shared_task

logger = logging.getLogger(__name__)

WEB_PUSH_SENDER_DISABLED_REASON = "web push sender disabled (flag off or VAPID keys missing)"
NOTIFICATION_MISSING_REASON = "notification row no longer exists"
SUBSCRIPTION_UNAVAILABLE_REASON = "subscription missing or not active"
SUBSCRIPTION_GONE_REASON = "subscription_gone"

#: How long the push service may hold an undelivered message. One day —
#: a notification older than that is stale by the time the device wakes.
WEB_PUSH_TTL_SECONDS = 86400

_MAX_ERROR_LENGTH = 500


@shared_task(
    name="notifications.deliver_web_push",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def deliver_web_push(self, notification_id):
    """Deliver a notification's deliverable web_push ledger rows."""
    from components.notifications.application.ports.web_push_sender_port import (
        SubscriptionGoneError,
        TransientPushError,
    )
    from components.notifications.application.providers.push_delivery_provider import (
        get_push_delivery_provider,
    )
    from components.notifications.domain.enums import DeliveryChannel
    from components.notifications.infrastructure.adapters.webpush_config import (
        get_vapid_private_key,
        web_push_enabled,
    )

    provider = get_push_delivery_provider()
    ledger = provider.delivery_ledger()

    # Flag-off / unprovisioned environments: truthful terminal no-op.
    if not web_push_enabled() or not get_vapid_private_key():
        pending = ledger.pending_for(
            notification_id=notification_id,
            channel=DeliveryChannel.WEB_PUSH.value,
        )
        for record in pending:
            ledger.mark_skipped(record.id, reason=WEB_PUSH_SENDER_DISABLED_REASON)
        if pending:
            logger.info(
                "deliver_web_push skipped (sender disabled) notification_id=%s rows=%d task_id=%s",
                notification_id,
                len(pending),
                self.request.id,
            )
        return {"notification_id": str(notification_id), "skipped": len(pending)}

    deliverable = ledger.deliverable_for(
        notification_id=notification_id,
        channel=DeliveryChannel.WEB_PUSH.value,
    )
    if not deliverable:
        return {"notification_id": str(notification_id), "sent": 0, "failed": 0, "skipped": 0}

    payload = _build_web_push_payload(notification_id)
    if payload is None:
        for record in deliverable:
            ledger.mark_skipped(record.id, reason=NOTIFICATION_MISSING_REASON)
        logger.warning(
            "deliver_web_push notification missing notification_id=%s rows=%d task_id=%s",
            notification_id,
            len(deliverable),
            self.request.id,
        )
        return {"notification_id": str(notification_id), "skipped": len(deliverable)}
    payload_json = json.dumps(payload)

    registry = provider.push_subscription_registry()
    sender = provider.web_push_sender()

    sent = failed = skipped = 0
    transient_error = None
    for record in deliverable:
        # Per-row isolation (sanctioned bulk-loop pattern, see
        # sponsorship ledger_tasks.py): one bad device must never block
        # delivery to the recipient's other devices.
        try:
            subscription = registry.get_by_id(record.subscription_id) if record.subscription_id else None
            if subscription is None or subscription.status != "active":
                ledger.mark_skipped(record.id, reason=SUBSCRIPTION_UNAVAILABLE_REASON)
                skipped += 1
                continue

            claimed = ledger.claim(record.id)
            if claimed is None:
                # Row went terminal since the fetch (concurrent run) — the
                # claim gate IS the double-send guard; nothing to do.
                continue

            try:
                sender.send(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": subscription.keys,
                    },
                    payload=payload_json,
                    ttl=WEB_PUSH_TTL_SECONDS,
                )
            except SubscriptionGoneError:
                # Terminal no-send: the device registration is dead. The
                # ledger's skipped state is its terminal no-retry outcome
                # (its port contract names "device expired"); failed would
                # be re-claimed by the next retry, which must not happen.
                registry.mark_expired(subscription.id)
                ledger.mark_skipped(record.id, reason=SUBSCRIPTION_GONE_REASON)
                skipped += 1
                logger.info(
                    "deliver_web_push subscription gone notification_id=%s delivery_id=%s subscription_id=%s",
                    notification_id,
                    record.id,
                    subscription.id,
                )
                continue
            except TransientPushError as exc:
                ledger.mark_failed(record.id, error=str(exc)[:_MAX_ERROR_LENGTH])
                failed += 1
                transient_error = exc
                logger.warning(
                    "deliver_web_push transient failure notification_id=%s delivery_id=%s attempts=%d",
                    notification_id,
                    record.id,
                    claimed.attempts,
                )
                continue

            ledger.mark_sent(record.id)
            sent += 1
        except Exception:
            logger.exception(
                "deliver_web_push row failed notification_id=%s delivery_id=%s",
                notification_id,
                record.id,
            )
            ledger.mark_failed(record.id, error="unexpected error during web push delivery")
            failed += 1
            continue

    logger.info(
        "deliver_web_push completed notification_id=%s sent=%d failed=%d skipped=%d task_id=%s",
        notification_id,
        sent,
        failed,
        skipped,
        self.request.id,
    )
    if transient_error is not None:
        # Whole batch processed first (per-row isolation); the retry
        # re-claims only the failed rows — sent/skipped stay terminal.
        raise self.retry(exc=transient_error)
    return {
        "notification_id": str(notification_id),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }


def _build_web_push_payload(notification_id) -> dict | None:
    """Build the browser-facing payload from the in-app notification row.

    Mirrors what the in-app feed renders: the actor's display name + the
    ``verb`` (the same fields ``NotificationSerializer`` exposes), the
    workspace name as the title, and the dispatch-time deep link from
    ``metadata["link"]`` — absolutized here with
    ``resolve_frontend_base_url()`` because the service worker opens it
    outside any app origin context. Returns None when the notification
    row no longer exists (deleted between dispatch and delivery).
    """
    from components.shared_platform.application.providers.core_utils_provider import (
        CoreUtilsProvider,
    )
    from infrastructure.persistence.notifications.models import Notification

    notification = Notification.objects.filter(pk=notification_id).select_related("actor", "workspace").first()
    if notification is None:
        return None

    actor = notification.actor
    actor_name = ""
    if actor is not None:
        actor_name = (actor.get_full_name() or actor.username or "").strip()
    body = f"{actor_name} {notification.verb}".strip() or notification.verb

    workspace = getattr(notification, "workspace", None)
    title = workspace.workspace_name if workspace else "New notification"

    link = None
    metadata = notification.metadata or {}
    relative = metadata.get("link")
    if isinstance(relative, str) and relative.startswith("/") and not relative.startswith("//"):
        base = CoreUtilsProvider().resolve_frontend_base_url()
        link = f"{base}{relative}"

    payload = {
        "title": title,
        "body": body,
        "link": link,
        "notification_id": str(notification.pk),
    }
    if notification.logo_url:
        payload["icon"] = notification.logo_url
    return payload
