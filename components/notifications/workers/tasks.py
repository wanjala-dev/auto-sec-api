"""Celery tasks for the notifications bounded context.

Includes beat-scheduled archival and async dispatch helpers.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# How many delivery-ledger rows to delete per DELETE statement — bounds the
# pk list Django materialises for constraint handling on very large backlogs
# (same batching pattern as identity.sweep_user_sessions' audit prune).
_PRUNE_BATCH_SIZE = 5000

# ---------------------------------------------------------------------------
# Archival
# ---------------------------------------------------------------------------

ARCHIVE_AGE_DAYS = 90


@shared_task(
    name="notifications.archive_old_notifications",
    soft_time_limit=240,
    time_limit=300,
)
def archive_old_notifications():
    """Soft-archive notifications older than ARCHIVE_AGE_DAYS.

    Runs daily via Celery Beat. Sets ``is_archived=True`` and records
    ``archived_at`` but never deletes rows — data is retained for
    audit and analytics.
    """
    from infrastructure.persistence.notifications.models import Notification

    cutoff = timezone.now() - timedelta(days=ARCHIVE_AGE_DAYS)
    qs = Notification.objects.filter(
        is_archived=False,
        created_at__lt=cutoff,
    )
    count = qs.update(is_archived=True, archived_at=timezone.now())
    if count:
        logger.info("Archived %d notifications older than %d days.", count, ARCHIVE_AGE_DAYS)
    return count


# ---------------------------------------------------------------------------
# Push/delivery hygiene
# ---------------------------------------------------------------------------


@shared_task(
    name="notifications.prune_stale_push_subscriptions",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=540,
    time_limit=600,
)
def prune_stale_push_subscriptions(self) -> dict[str, int]:
    """Weekly push-registry + delivery-ledger janitor. Idempotent — pure
    reconciliation, mirrors ``identity.sweep_user_sessions``.

    1. ``PushSubscription`` rows already dead (``expired``/``revoked``) whose
       last touch (``updated_at``) is older than
       ``PUSH_SUBSCRIPTION_PRUNE_AFTER_DAYS`` are deleted. The delivery
       ledger's ``subscription`` FK is SET_NULL, so ledger history survives
       the registry row.
    2. ``active`` subscriptions not seen for
       ``PUSH_SUBSCRIPTION_STALE_AFTER_DAYS`` (``last_seen_at``; falls back
       to ``created_at`` for never-seen rows) are marked ``expired`` — not
       deleted. ``updated_at`` is stamped explicitly (queryset ``update()``
       bypasses ``auto_now``) so they age into rule 1's deletion window a
       further PRUNE_AFTER_DAYS later.
    3. ``NotificationDelivery`` rows in a terminal state
       (``sent``/``skipped``/``failed``) older than
       ``NOTIFICATION_DELIVERY_RETENTION_DAYS`` are deleted in batches.
       Non-terminal (``pending``) rows and the ``Notification`` rows
       themselves are untouched.
    """
    from django.conf import settings
    from django.db.models import Q

    from infrastructure.persistence.notifications.models import (
        NotificationDelivery,
        PushSubscription,
    )

    logger.info("notifications.prune_stale_push_subscriptions started task_id=%s", self.request.id)

    now = timezone.now()
    dead_cutoff = now - timedelta(days=int(settings.PUSH_SUBSCRIPTION_PRUNE_AFTER_DAYS))
    stale_cutoff = now - timedelta(days=int(settings.PUSH_SUBSCRIPTION_STALE_AFTER_DAYS))
    delivery_cutoff = now - timedelta(days=int(settings.NOTIFICATION_DELIVERY_RETENTION_DAYS))

    # 1. Delete long-dead subscriptions. Runs BEFORE the expiry pass so rows
    #    freshly expired below get their full retention window.
    subscriptions_pruned, _ = PushSubscription.objects.filter(
        status__in=(PushSubscription.Status.EXPIRED, PushSubscription.Status.REVOKED),
        updated_at__lt=dead_cutoff,
    ).delete()

    # 2. Expire stale-but-active subscriptions. ``updated_at=now`` is set
    #    explicitly because ``update()`` skips ``auto_now`` — without it a
    #    long-untouched row would be deleted by rule 1 on the very next run.
    subscriptions_expired = PushSubscription.objects.filter(
        Q(last_seen_at__lt=stale_cutoff) | Q(last_seen_at__isnull=True, created_at__lt=stale_cutoff),
        status=PushSubscription.Status.ACTIVE,
    ).update(status=PushSubscription.Status.EXPIRED, updated_at=now)

    # 3. Prune terminal ledger rows past retention, batched so a first run
    #    over a large backlog doesn't materialise millions of pks at once.
    deliveries_pruned = 0
    terminal = (
        NotificationDelivery.Status.SENT,
        NotificationDelivery.Status.SKIPPED,
        NotificationDelivery.Status.FAILED,
    )
    while True:
        batch_ids = list(
            NotificationDelivery.objects.filter(
                status__in=terminal,
                created_at__lt=delivery_cutoff,
            ).values_list("pk", flat=True)[:_PRUNE_BATCH_SIZE]
        )
        if not batch_ids:
            break
        deleted, _ = NotificationDelivery.objects.filter(pk__in=batch_ids).delete()
        deliveries_pruned += deleted

    result = {
        "subscriptions_pruned": subscriptions_pruned,
        "subscriptions_expired": subscriptions_expired,
        "deliveries_pruned": deliveries_pruned,
    }
    logger.info(
        "notifications.prune_stale_push_subscriptions completed task_id=%s "
        "subscriptions_pruned=%d subscriptions_expired=%d deliveries_pruned=%d",
        self.request.id,
        subscriptions_pruned,
        subscriptions_expired,
        deliveries_pruned,
    )
    return result


# ---------------------------------------------------------------------------
# Async notification dispatch
# ---------------------------------------------------------------------------


@shared_task(
    name="notifications.dispatch_notification_async",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def dispatch_notification_async(
    self,
    *,
    recipient_id,
    actor_id,
    verb,
    notification_type,
    workspace_id=None,
    metadata=None,
    logo_url=None,
    target_ref=None,
    allow_self_notify=False,
    link=None,
):
    """Create an in-app notification asynchronously.

    Called via ``transaction.on_commit()`` so the triggering entity is
    guaranteed to be committed before the task runs.

    ``target_ref`` is a ``[app_label, model_name, pk]`` triple rehydrated into
    the GenericFK target here — model instances must never cross the Celery
    boundary (pass IDs, not objects — .claude/rules/celery-tasks.md).

    ``link`` is an optional explicit relative frontend path; when absent one
    is resolved from (type, target, workspace, metadata) AFTER target
    rehydration, and written into ``metadata["link"]`` before row creation so
    the in-app row, the realtime envelope, and push payloads all carry it.
    """
    from django.contrib.auth import get_user_model

    from components.notifications.infrastructure.adapters.utils import (
        create_notification,
    )

    User = get_user_model()
    try:
        recipient = User.objects.get(pk=recipient_id)
        actor = User.objects.get(pk=actor_id)
    except User.DoesNotExist:
        logger.warning(
            "Skipping notification — recipient %s or actor %s not found.",
            recipient_id,
            actor_id,
        )
        return None

    workspace = None
    if workspace_id:
        from infrastructure.persistence.workspaces.models import Workspace

        workspace = Workspace.objects.filter(id=workspace_id).first()

    target = None
    if target_ref:
        from django.apps import apps as django_apps

        try:
            app_label, model_name, target_pk = target_ref
            model = django_apps.get_model(app_label, model_name)
            target = model.objects.filter(pk=target_pk).first()
        except (LookupError, ValueError):
            logger.warning(
                "dispatch_notification_async could not rehydrate target_ref=%s "
                "recipient_id=%s — creating notification without target.",
                target_ref,
                recipient_id,
            )

    # Deep link — explicit ``link=`` wins; otherwise resolve from the
    # (type, rehydrated target, workspace, metadata) tuple. Written into
    # metadata BEFORE row creation so the row, the WS envelope, and future
    # push payloads all carry the same relative frontend path. Metadata is
    # not part of the dedup identity, so this cannot split dedup groups.
    from components.notifications.infrastructure.adapters.link_resolver import (
        resolve_link,
    )

    metadata = dict(metadata or {})
    resolved_link = link or resolve_link(
        notification_type,
        target=target,
        workspace_id=workspace_id,
        metadata=metadata,
    )
    if resolved_link:
        metadata["link"] = resolved_link

    notification = create_notification(
        recipient=recipient,
        actor=actor,
        verb=verb,
        notification_type=notification_type,
        target=target,
        workspace=workspace,
        metadata=metadata,
        logo_url=logo_url,
        allow_self_notify=allow_self_notify,
    )
    # Return a JSON-serializable id, NOT the ORM instance. Celery
    # serializes task return values into the result backend (Redis) as
    # JSON by default — handing back a Notification model raises
    # ``EncodeError: Object of type Notification is not JSON
    # serializable``. The 2026-05-27 demo run caught this when the
    # report-generated → recipient notification step crashed and the
    # user never saw a 'Report ready' toast. Rule from
    # .claude/rules/celery-tasks.md: pass IDs, never objects.
    if notification is None:
        return None

    _publish_created_event(notification, recipient, workspace_id)
    _record_channel_deliveries(notification, recipient)
    return {"notification_id": str(getattr(notification, "id", "") or "")}


def _publish_created_event(notification, recipient, workspace_id):
    """Realtime leg of the funnel — push the fresh row + unread count to
    the recipient's ``user.<id>.notifications`` group.

    Loss-tolerant by design: the in-app row (created above) is the source
    of truth; a websocket miss self-heals on the next connect/fetch. The
    adapter no-ops when NOTIFICATIONS_REALTIME_ENABLED is off or the
    channel layer is unavailable.
    """
    try:
        from components.notifications.application.ports.notification_channel_port import (
            NOTIFICATION_CREATED,
            NotificationEvent,
        )
        from components.notifications.infrastructure.adapters.cache import (
            get_unread_count,
        )
        from components.notifications.infrastructure.adapters.realtime_notification_channel import (
            RealtimeNotificationChannel,
        )
        from components.notifications.mappers.rest.notification_serializers import (
            NotificationSerializer,
        )

        RealtimeNotificationChannel().deliver(
            NotificationEvent(
                event_name=NOTIFICATION_CREATED,
                recipient_id=str(recipient.pk),
                notification_id=str(notification.id),
                workspace_id=str(workspace_id) if workspace_id else None,
                unread_count=get_unread_count(recipient),
                notification=NotificationSerializer(notification).data,
            )
        )
    except Exception:
        logger.exception(
            "notification_realtime_created_publish_failed notification_id=%s recipient_id=%s",
            getattr(notification, "id", None),
            getattr(recipient, "pk", None),
        )


def _record_channel_deliveries(notification, recipient):
    """Per-channel fan-out leg of the funnel (T1-S5 web_push, T1-S8 email).

    Consults ``channels_for(recipient)`` (realtime always-on; web_push /
    email gated by the revived ``UserPreference`` booleans) and records
    delivery-ledger rows for opted-in channels, then enqueues the
    per-channel delivery task:

    * ``web_push`` — one pending ``NotificationDelivery`` per active web
      subscription, delivered by ``notifications.deliver_web_push`` (the
      real pywebpush sender since T1-S6; a truthful skip when the
      flag/keys are off).
    * ``email`` — high-value types only (``EMAIL_WORTHY_TYPES`` domain
      policy): ONE pending row (subscription NULL — the conditional unique
      constraint is the DB-level dedup), delivered by
      ``notifications.deliver_email`` through the shared email layer
      (a truthful skip while ``NOTIF_EMAIL_CHANNEL_ENABLED`` is off).

    Each sender is enqueued only when a NEW row was recorded — the unique
    keys make a retried dispatch converge instead of double-enqueueing.

    Loss-tolerant like the realtime leg: the in-app row is the source of
    truth, so a ledger/bookkeeping failure is logged, never raised.
    """
    try:
        from components.notifications.application.providers.push_delivery_provider import (
            get_push_delivery_provider,
        )
        from components.notifications.domain.enums import DeliveryChannel, PushPlatform
        from components.notifications.domain.policies.delivery_channel_policy import (
            is_email_worthy,
        )

        provider = get_push_delivery_provider()
        channels = provider.channels_for(recipient)
        ledger = provider.delivery_ledger()

        if DeliveryChannel.WEB_PUSH.value in channels:
            subscriptions = provider.push_subscription_registry().list_active_for_user(
                recipient.pk,
                platform=PushPlatform.WEB.value,
            )
            recorded_new = False
            for subscription in subscriptions:
                outcome = ledger.record(
                    notification_id=notification.id,
                    channel=DeliveryChannel.WEB_PUSH.value,
                    subscription_id=subscription.id,
                )
                recorded_new = recorded_new or outcome.created

            if recorded_new:
                from components.notifications.infrastructure.tasks.web_push_tasks import (
                    deliver_web_push,
                )

                deliver_web_push.delay(notification_id=notification.id)

        if DeliveryChannel.EMAIL.value in channels and is_email_worthy(notification.notification_type):
            outcome = ledger.record(
                notification_id=notification.id,
                channel=DeliveryChannel.EMAIL.value,
            )
            if outcome.created:
                from components.notifications.infrastructure.tasks.email_tasks import (
                    deliver_email,
                )

                deliver_email.delay(notification_id=notification.id)
    except Exception:
        logger.exception(
            "notification_channel_delivery_record_failed notification_id=%s recipient_id=%s",
            getattr(notification, "id", None),
            getattr(recipient, "pk", None),
        )
