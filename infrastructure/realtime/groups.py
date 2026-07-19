"""Canonical Channels group-name helpers.

Both the publisher (``ChannelsRealtimeEventAdapter`` in
``components/shared_platform/infrastructure/adapters/``) and the
consumers (``ResourceStreamConsumer`` / ``WorkspaceActivityConsumer``
in ``infrastructure/realtime/consumers.py``) need to agree on group
names byte-for-byte — a typo on either side and the publish lands
in a different group than the consumer joined, which silently breaks
realtime delivery without raising.

Centralised here so a future shape change can't drift between sender
and receiver.

**Why no ``:`` separator.** ``channels_redis``'s ``RedisChannelLayer``
validates group names against ``[A-Za-z0-9._-]`` (see
``channels.layers.BaseChannelLayer.valid_group_name``). The original
helpers used ``resource:<type>:<id>`` and ``workspace:<id>:activity``
which both contain ``:`` characters that the validator rejects with
a TypeError. The publisher caught + logged the exception (publish is
best-effort), so the runtime symptom was: chat-progress events save
to ``DeepRunLog`` correctly but never reach connected WebSocket
clients. Switching the separator to ``.`` keeps the names readable
in logs, satisfies the validator, and stays compatible with the
``::`` ancestor pattern used elsewhere.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md`` Phase 7.1.
"""

from __future__ import annotations


def resource_group(resource_type: str, resource_id: str) -> str:
    """Channel-layer group for a single resource event stream.

    Drives the agent-run progress UI, document-upload progress, etc.
    Same name on both ends — publisher inside
    ``ChannelsRealtimeEventAdapter`` and consumer inside
    ``ResourceStreamConsumer`` — so a publish lands in the same
    group the connected client joined.
    """
    return f"resource.{resource_type}.{resource_id}"


def workspace_activity_group(workspace_id: str) -> str:
    """Channel-layer group for a workspace's activity feed.

    Drives the dashboard "what's happening across this workspace"
    panel. Joined by ``WorkspaceActivityConsumer``; published to by
    every resource event that carries a ``workspace_id``.
    """
    return f"workspace.{workspace_id}.activity"


def user_notifications_group(user_id: str) -> str:
    """Channel-layer group for a single user's notification stream.

    USER-SCOPED like the sponsor feed: joined by ``NotificationConsumer``
    keyed off ``scope["user"].id`` (never the URL), so a user can only
    ever receive their own notification events. Published to by
    ``RealtimeNotificationChannel`` — the realtime leg of the
    notification dispatcher funnel (created / read / all-read events +
    fresh unread counts for the header badge).
    """
    return f"user.{user_id}.notifications"


def sponsor_feed_group(user_id: str) -> str:
    """Channel-layer group for a single donor's private transparency feed.

    DONOR-SCOPED, not workspace-scoped: a sponsor watches only THEIR OWN
    money move (donation received, sponsorship charged, funds spent on
    their behalf, balance updated) across every org they support. Joined
    by ``SponsorFeedConsumer`` keyed off ``scope["user"].id`` (never the
    URL), so one donor can never subscribe to another's feed. Published
    to by the sponsorship realtime handlers, which resolve the affected
    donor (payer / income-source email -> user) before publishing here.
    """
    return f"sponsor.{user_id}.feed"
