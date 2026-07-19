"""Celery tasks for the notifications bounded context.

Includes beat-scheduled archival and async dispatch helpers.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

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
):
    """Create an in-app notification asynchronously.

    Called via ``transaction.on_commit()`` so the triggering entity is
    guaranteed to be committed before the task runs.

    ``target_ref`` is a ``[app_label, model_name, pk]`` triple rehydrated into
    the GenericFK target here — model instances must never cross the Celery
    boundary (pass IDs, not objects — .claude/rules/celery-tasks.md).
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

    notification = create_notification(
        recipient=recipient,
        actor=actor,
        verb=verb,
        notification_type=notification_type,
        target=target,
        workspace=workspace,
        metadata=metadata or {},
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
