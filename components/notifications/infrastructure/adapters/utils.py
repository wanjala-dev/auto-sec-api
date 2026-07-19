from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, router
from django.utils import timezone

from infrastructure.persistence.notifications.models import Notification

User = get_user_model()
DEFAULT_DEDUPLICATION_WINDOW = timedelta(minutes=5)
logger = logging.getLogger(__name__)


def create_notification(
    *,
    recipient,
    actor,
    verb: str,
    notification_type: str,
    target=None,
    workspace=None,
    metadata: dict | None = None,
    deduplicate: bool = True,
    deduplication_window: timedelta = DEFAULT_DEDUPLICATION_WINDOW,
    logo_url: str | None = None,
    allow_self_notify: bool = False,
):
    """Create (or reuse) a notification for ``recipient``.

    Mirrors the approach described in the product brief: prevent duplicate
    notifications within a short window and gracefully no-op when the actor
    and recipient are the same person.

    ``allow_self_notify`` opts out of the actor == recipient no-op for
    system-generated events where the owner legitimately stands in as the
    actor (workflow run finished, report ready, security alerts, bank-feed
    lifecycle, import completed). Without it those notifications silently
    vanish — the historical reason several contexts bypassed this funnel
    with raw ``Notification.objects.create`` calls.
    """
    if recipient is None or actor is None:
        raise ValueError("recipient and actor are required for notifications")

    if recipient == actor and not allow_self_notify:
        return None

    # Ensure recipient and actor exist in the database before creating notification
    # This prevents IntegrityError when they haven't been committed yet
    if not getattr(recipient, "pk", None) or not getattr(actor, "pk", None):
        return None

    db_alias = router.db_for_write(Notification)
    user_qs = User.objects.using(db_alias)
    if not user_qs.filter(pk=recipient.pk).exists():
        return None
    if not user_qs.filter(pk=actor.pk).exists():
        return None

    metadata = metadata or {}

    content_type = None
    object_id = None
    if target is not None:
        content_type = ContentType.objects.get_for_model(target, for_concrete_model=False)
        object_id = target.pk

    # The verb is part of the dedup identity: two DIFFERENT events from the
    # same actor within the window (e.g. auth "reset requested" then "reset
    # completed", both SYSTEM/no-target) must both land. Repeats of the SAME
    # action produce the same verb string and still dedup.
    queryset = Notification.objects.filter(
        recipient=recipient,
        actor=actor,
        notification_type=notification_type,
        workspace=workspace,
        verb=verb,
    )

    if content_type is None:
        queryset = queryset.filter(content_type__isnull=True, object_id__isnull=True)
    else:
        queryset = queryset.filter(content_type=content_type, object_id=object_id)

    if deduplicate:
        window_start = timezone.now() - deduplication_window
        existing = queryset.filter(created_at__gte=window_start).first()
        if existing:
            return existing

    try:
        return Notification.objects.create(
            recipient=recipient,
            actor=actor,
            verb=verb,
            notification_type=notification_type,
            content_type=content_type,
            object_id=object_id,
            metadata=metadata,
            workspace=workspace,
            logo_url=logo_url,
        )
    except IntegrityError as exc:
        logger.warning(
            "Skipping notification due to integrity error (recipient=%s, actor=%s): %s",
            getattr(recipient, "pk", None),
            getattr(actor, "pk", None),
            exc,
        )
        return None
