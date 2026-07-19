"""Channels-backed implementation of ``RealtimeEventPort``.

Publishes a single ``resource.event`` envelope to two channel-layer
groups:

    - ``resource.<resource_type>.<resource_id>`` — per-resource detail
      stream (drives the agent-run progress UI, upload progress, etc.).
    - ``workspace.<workspace_id>.activity`` — per-workspace activity
      feed (drives the dashboard "what's happening" panel).

Either subscriber missing is fine — Channels' ``group_send`` is a
no-op when nobody's listening.

Group-name helpers live in ``infrastructure/realtime/groups.py`` so
the publisher and the WebSocket consumers can't drift. Original
helpers used ``:`` separators which the Redis Channels layer rejects
in ``BaseChannelLayer.valid_group_name`` (only ``[A-Za-z0-9._-]`` is
allowed) — see the helper module for the full incident note.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md`` Phase 7.1.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Mapping, Optional

from components.shared_platform.application.ports.realtime_event_port import (
    RealtimeEventPort,
)
from infrastructure.realtime.groups import (
    resource_group,
    sponsor_feed_group,
    workspace_activity_group,
)

logger = logging.getLogger(__name__)


class ChannelsRealtimeEventAdapter(RealtimeEventPort):
    """Publish via the Channels channel layer.

    The adapter is intentionally tolerant of missing infrastructure —
    if ``channels`` isn't installed, or the channel layer isn't
    configured, ``publish`` logs and returns. This keeps publisher
    sites (signal bridges, Celery tasks) from crashing when running
    under tests or in environments without Redis. The ``NoOp`` adapter
    is the explicit "off" switch for tests.
    """

    def publish(
        self,
        *,
        workspace_id: str,
        resource_type: str,
        resource_id: str,
        event_name: str,
        status: str,
        progress_percent: int = 0,
        payload: Optional[Mapping[str, object]] = None,
    ) -> None:
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
        except ImportError:
            logger.debug(
                "channels_realtime_publish_skipped reason=missing_channels "
                "resource_type=%s resource_id=%s",
                resource_type,
                resource_id,
            )
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.debug(
                "channels_realtime_publish_skipped reason=no_layer "
                "resource_type=%s resource_id=%s",
                resource_type,
                resource_id,
            )
            return

        envelope = {
            "type": "resource.event",
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "workspace_id": str(workspace_id) if workspace_id else "",
            "status": status,
            "progress_percent": int(progress_percent or 0),
            "event_name": event_name,
            "payload": dict(payload or {}),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

        # Channel-layer message MUST have a ``type`` key matching the
        # consumer handler method (replacing dots with underscores).
        # Our consumers handle ``resource_event`` so we publish that.
        message = {"type": "resource.event", "envelope": envelope}

        groups = [resource_group(resource_type, resource_id)]
        if workspace_id:
            groups.append(workspace_activity_group(workspace_id))

        for group in groups:
            try:
                async_to_sync(channel_layer.group_send)(group, message)
            except Exception:  # noqa: BLE001
                # A failure to publish must never break the upstream
                # work (saving a DeepRunLog, finishing an upload).
                # Log + continue with the next group.
                logger.exception(
                    "channels_realtime_publish_failed group=%s "
                    "resource_type=%s resource_id=%s",
                    group,
                    resource_type,
                    resource_id,
                )


    def publish_to_sponsor_feed(
        self,
        *,
        user_id: str,
        event_name: str,
        payload: Optional[Mapping[str, object]] = None,
        workspace_id: str = "",
    ) -> None:
        if not user_id:
            return
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
        except ImportError:
            logger.debug(
                "sponsor_feed_publish_skipped reason=missing_channels user_id=%s",
                user_id,
            )
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.debug(
                "sponsor_feed_publish_skipped reason=no_layer user_id=%s", user_id
            )
            return

        envelope = {
            "type": "resource.event",
            "resource_type": "sponsor_feed",
            "resource_id": str(user_id),
            "workspace_id": str(workspace_id) if workspace_id else "",
            "status": "",
            "progress_percent": 0,
            "event_name": event_name,
            "payload": dict(payload or {}),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        message = {"type": "resource.event", "envelope": envelope}
        group = sponsor_feed_group(user_id)
        try:
            async_to_sync(channel_layer.group_send)(group, message)
        except Exception:  # noqa: BLE001
            logger.exception(
                "sponsor_feed_publish_failed group=%s event_name=%s",
                group,
                event_name,
            )


class NoOpRealtimeEventAdapter(RealtimeEventPort):
    """Test / fallback adapter — drops every publish silently.

    Used by tests that don't want to set up the channel layer, and as
    the safe default when the realtime stack isn't booted (CLI scripts,
    one-shot management commands, etc.)."""

    def publish(self, **kwargs) -> None:
        return None
