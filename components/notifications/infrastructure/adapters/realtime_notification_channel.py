"""Channels-backed notification delivery — the realtime leg of the funnel.

Publishes ``notification.event`` envelopes to the recipient's private
channel-layer group (``user.<id>.notifications``, joined by
``NotificationConsumer`` at ``/ws/notifications/``) so the badge, the
recent-dropdown, and the feed update live without polling.

Mirrors ``ChannelsRealtimeEventAdapter``'s tolerant-publish posture: a
failed or impossible publish (no channels, no layer, Redis down) logs
and returns — the in-app Notification row is the source of truth and
websocket delivery is loss-tolerant by design (the REST list backfills
on the next connect/fetch).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from components.notifications.application.ports.notification_channel_port import (
    NotificationChannelPort,
    NotificationEvent,
)
from infrastructure.realtime.groups import user_notifications_group

logger = logging.getLogger(__name__)


class RealtimeNotificationChannel(NotificationChannelPort):
    """Publish notification events via the Channels channel layer."""

    def deliver(self, event: NotificationEvent) -> None:
        from django.conf import settings

        if not getattr(settings, "NOTIFICATIONS_REALTIME_ENABLED", True):
            return
        if not event.recipient_id:
            return

        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
        except ImportError:
            logger.debug(
                "notification_realtime_publish_skipped reason=missing_channels recipient_id=%s event=%s",
                event.recipient_id,
                event.event_name,
            )
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.debug(
                "notification_realtime_publish_skipped reason=no_layer recipient_id=%s event=%s",
                event.recipient_id,
                event.event_name,
            )
            return

        envelope = {
            "type": "notification.event",
            "event_name": event.event_name,
            "notification_id": str(event.notification_id) if event.notification_id else None,
            "workspace_id": str(event.workspace_id) if event.workspace_id else None,
            "notification": dict(event.notification) if event.notification else None,
            "unread_count": self._resolve_unread_count(event),
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
        # Channel-layer ``type`` maps to the consumer handler method with
        # dots replaced by underscores — NotificationConsumer.notification_event.
        message = {"type": "notification.event", "envelope": envelope}
        group = user_notifications_group(str(event.recipient_id))

        try:
            async_to_sync(channel_layer.group_send)(group, message)
        except Exception:
            logger.exception(
                "notification_realtime_publish_failed group=%s event=%s recipient_id=%s",
                group,
                event.event_name,
                event.recipient_id,
            )

    def _resolve_unread_count(self, event: NotificationEvent) -> int | None:
        """Fresh global unread count for the recipient.

        Emitters that already hold the recipient user pass the count in;
        read-state emitters (mark-read use cases) only know the id, so
        compute it here through the same cached helper the REST
        ``unread_count`` endpoint uses — one number, one source.
        """
        if event.unread_count is not None:
            return int(event.unread_count)
        try:
            from django.contrib.auth import get_user_model

            from components.notifications.infrastructure.adapters.cache import (
                get_unread_count,
            )

            user = get_user_model().objects.filter(pk=event.recipient_id).first()
            if user is None:
                return None
            return get_unread_count(user)
        except Exception:
            logger.exception(
                "notification_realtime_unread_count_failed recipient_id=%s",
                event.recipient_id,
            )
            return None
