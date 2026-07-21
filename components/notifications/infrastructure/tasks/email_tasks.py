"""Email delivery task (T1-S8 — the email channel on the delivery ledger).

The dispatch funnel records ONE pending ``NotificationDelivery`` row per
notification (channel=email, subscription NULL — deduped at the DB by the
conditional unique constraint) for email-worthy types when the recipient's
``email_notifications`` preference is on, then enqueues this task. The task
claims the deliverable ledger row and sends through the canonical shared
email layer (``get_email_adapter_provider().adapter().send_templated``) —
never a hand-rolled ``EmailMultiAlternatives``.

Outcomes per row (mirrors ``web_push_tasks``):

    sent               the email backend accepted the message
    skipped            flag off, notification row gone, or the recipient
                       has no email address. Terminal, never retried.
    failed             the backend reported a send failure (SMTP/SES errors
                       surface as a False return from the adapter — it sends
                       fail-silently) — transient; the task re-raises for
                       Celery retry and the retry re-claims failed rows via
                       ``deliverable_for``. Unexpected in-process errors
                       (template rendering, data bugs) also mark failed but
                       do NOT retry — retrying a deterministic bug is noise.

Flag OFF (``NOTIF_EMAIL_CHANNEL_ENABLED`` false) stays a truthful no-op:
pending rows transition to ``skipped`` with an explicit reason — the ledger
never claims a send that didn't happen.

Email bodies carry user content — log ids and counts only, never the
subject, body, or recipient address.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

EMAIL_CHANNEL_DISABLED_REASON = "email channel disabled (NOTIF_EMAIL_CHANNEL_ENABLED off)"
NOTIFICATION_MISSING_REASON = "notification row no longer exists"
RECIPIENT_EMAIL_MISSING_REASON = "recipient has no email address"
EMAIL_SEND_FAILED_ERROR = "email backend reported send failure"

NOTIFICATION_EMAIL_TEMPLATE = "email/notification_alert.html"

_MAX_ERROR_LENGTH = 500


class TransientEmailDeliveryError(Exception):
    """Raised to hand a backend send failure to Celery's retry machinery."""


@shared_task(
    name="notifications.deliver_email",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def deliver_email(self, notification_id):
    """Deliver a notification's deliverable email ledger rows."""
    from components.notifications.application.providers.push_delivery_provider import (
        get_push_delivery_provider,
    )
    from components.notifications.domain.enums import DeliveryChannel
    from components.notifications.infrastructure.adapters.email_channel_config import (
        notification_email_enabled,
    )

    provider = get_push_delivery_provider()
    ledger = provider.delivery_ledger()

    # Flag-off environments: truthful terminal no-op.
    if not notification_email_enabled():
        pending = ledger.pending_for(
            notification_id=notification_id,
            channel=DeliveryChannel.EMAIL.value,
        )
        for record in pending:
            ledger.mark_skipped(record.id, reason=EMAIL_CHANNEL_DISABLED_REASON)
        if pending:
            logger.info(
                "deliver_email skipped (channel disabled) notification_id=%s rows=%d task_id=%s",
                notification_id,
                len(pending),
                self.request.id,
            )
        return {"notification_id": str(notification_id), "skipped": len(pending)}

    deliverable = ledger.deliverable_for(
        notification_id=notification_id,
        channel=DeliveryChannel.EMAIL.value,
    )
    if not deliverable:
        return {"notification_id": str(notification_id), "sent": 0, "failed": 0, "skipped": 0}

    notification = _load_notification(notification_id)
    if notification is None:
        for record in deliverable:
            ledger.mark_skipped(record.id, reason=NOTIFICATION_MISSING_REASON)
        logger.warning(
            "deliver_email notification missing notification_id=%s rows=%d task_id=%s",
            notification_id,
            len(deliverable),
            self.request.id,
        )
        return {"notification_id": str(notification_id), "skipped": len(deliverable)}

    to_email = (getattr(notification.recipient, "email", "") or "").strip()
    if not to_email:
        for record in deliverable:
            ledger.mark_skipped(record.id, reason=RECIPIENT_EMAIL_MISSING_REASON)
        logger.info(
            "deliver_email recipient email missing notification_id=%s recipient_id=%s rows=%d",
            notification_id,
            notification.recipient_id,
            len(deliverable),
        )
        return {"notification_id": str(notification_id), "skipped": len(deliverable)}

    subject, context = _build_email_content(notification)

    from components.shared_platform.application.providers.email_adapter_provider import (
        get_email_adapter_provider,
    )

    adapter = get_email_adapter_provider().adapter()

    sent = failed = skipped = 0
    transient_failure = False
    # The dedup constraint makes one row per notification the norm, but the
    # loop keeps parity with the ledger contract (deliverable_for returns a
    # list) and with the web_push task's per-row isolation pattern.
    for record in deliverable:
        claimed = ledger.claim(record.id)
        if claimed is None:
            # Row went terminal since the fetch (concurrent run) — the claim
            # gate IS the double-send guard; nothing to do.
            continue
        try:
            delivered = adapter.send_templated(
                to=[to_email],
                subject=subject,
                template=NOTIFICATION_EMAIL_TEMPLATE,
                context=context,
                workspace_id=notification.workspace_id,
            )
        except Exception:
            # Deterministic in-process failure (template/context bug) —
            # mark failed for the audit trail but don't retry a bug.
            logger.exception(
                "deliver_email row failed notification_id=%s delivery_id=%s",
                notification_id,
                record.id,
            )
            ledger.mark_failed(record.id, error="unexpected error during email delivery"[:_MAX_ERROR_LENGTH])
            failed += 1
            continue

        if delivered:
            ledger.mark_sent(record.id)
            sent += 1
        else:
            # The shared adapter sends fail-silently and returns False on
            # SMTP/SES-level failures — transient; retry re-claims the row.
            ledger.mark_failed(record.id, error=EMAIL_SEND_FAILED_ERROR)
            failed += 1
            transient_failure = True
            logger.warning(
                "deliver_email transient failure notification_id=%s delivery_id=%s attempts=%d",
                notification_id,
                record.id,
                claimed.attempts,
            )

    logger.info(
        "deliver_email completed notification_id=%s sent=%d failed=%d skipped=%d task_id=%s",
        notification_id,
        sent,
        failed,
        skipped,
        self.request.id,
    )
    if transient_failure:
        raise self.retry(exc=TransientEmailDeliveryError(EMAIL_SEND_FAILED_ERROR))
    return {
        "notification_id": str(notification_id),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }


def _load_notification(notification_id):
    from infrastructure.persistence.notifications.models import Notification

    return Notification.objects.filter(pk=notification_id).select_related("actor", "workspace", "recipient").first()


def _build_email_content(notification) -> tuple[str, dict]:
    """Build (subject, template context) from the in-app notification row.

    Mirrors what the in-app feed renders: actor display name + ``verb``
    (the same fields ``NotificationSerializer`` exposes), the workspace
    name, and the dispatch-time deep link from ``metadata["link"]`` —
    absolutized with ``resolve_frontend_base_url()`` because email clients
    open links outside any app origin context.
    """
    from django.conf import settings

    from components.shared_platform.application.providers.core_utils_provider import (
        CoreUtilsProvider,
    )

    actor = notification.actor
    actor_name = ""
    if actor is not None:
        actor_name = (actor.get_full_name() or actor.username or "").strip()
    summary = f"{actor_name} {notification.verb}".strip() or notification.verb

    workspace = getattr(notification, "workspace", None)
    workspace_name = workspace.workspace_name if workspace else ""

    link_url = None
    metadata = notification.metadata or {}
    relative = metadata.get("link")
    if isinstance(relative, str) and relative.startswith("/") and not relative.startswith("//"):
        base = CoreUtilsProvider().resolve_frontend_base_url()
        link_url = f"{base}{relative}"

    site_name = getattr(settings, "SITE_NAME", "Octopus")
    subject = f"[{workspace_name}] {summary}" if workspace_name else summary

    context = {
        "site_name": site_name,
        "summary": summary,
        "actor_name": actor_name,
        "verb": notification.verb,
        "workspace_name": workspace_name,
        "link_url": link_url,
    }
    if notification.logo_url:
        context["workspace_logo_url"] = notification.logo_url
    return subject, context
