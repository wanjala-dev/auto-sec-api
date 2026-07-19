"""WebSocket consumers — Phase 7.0 + 7.1.

``PingConsumer`` exists to validate the auth + transport plumbing.
``ResourceStreamConsumer`` is the generic per-resource event channel
that powers the agent-run dashboard, document-upload progress, etc.

See ``docs/plans/REALTIME_OBSERVABILITY_PLAN.md``.
"""

from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

# Group-name helpers are now in a single shared module so the publisher
# (ChannelsRealtimeEventAdapter) and these consumers can't drift apart.
# Original ``:`` separator was rejected by Channels' Redis layer
# (``valid_group_name`` allows only ``[A-Za-z0-9._-]``) — every publish
# silently failed in production. See infrastructure/realtime/groups.py.
from infrastructure.realtime.groups import (
    resource_group as _resource_group,
)
from infrastructure.realtime.groups import (
    sponsor_feed_group as _sponsor_feed_group,
)
from infrastructure.realtime.groups import (
    user_notifications_group as _user_notifications_group,
)
from infrastructure.realtime.groups import (
    workspace_activity_group as _workspace_group,
)

logger = logging.getLogger(__name__)


class PingConsumer(AsyncJsonWebsocketConsumer):
    """Smoke-test consumer at ``/ws/ping/`` — echoes whatever payload
    is sent. Used to verify the JWT handshake + nginx routing before
    real consumers go live. Kept available in prod (cheap, useful)."""

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return
        await self.accept()
        await self.send_json({"type": "ping.ready", "user_id": str(user.id)})

    async def receive_json(self, content, **kwargs):
        await self.send_json({"type": "ping.echo", "payload": content})


class ResourceStreamConsumer(AsyncJsonWebsocketConsumer):
    """Per-resource event stream.

    URL: ``/ws/workspaces/<workspace_id>/resources/<resource_type>/<resource_id>/``

    Joins the resource group and pushes every event published for that
    resource. Frontend uses this to replace the polling loops on
    ``DeepRun`` events, document uploads, budget imports, etc.

    Authorisation: requires authenticated user. Workspace-scoped
    membership check is deferred to a follow-up — for the initial
    rollout, any authenticated user with the workspace_id can join
    that resource's stream. Tightening the gate to active membership
    is on the Phase 7.1 todo list.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.workspace_id = self.scope["url_route"]["kwargs"]["workspace_id"]
        self.resource_type = self.scope["url_route"]["kwargs"]["resource_type"]
        self.resource_id = self.scope["url_route"]["kwargs"]["resource_id"]
        self.group_name = _resource_group(self.resource_type, self.resource_id)

        if not await self._is_workspace_member(user.id, self.workspace_id):
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "resource.stream.ready",
                "resource_type": self.resource_type,
                "resource_id": self.resource_id,
            }
        )

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.exception(
                    "ws_resource_disconnect_group_discard_failed group=%s",
                    self.group_name,
                )

    async def resource_event(self, event):
        """Channel-layer handler — receives ``resource.event`` group
        messages and forwards them to the connected client."""
        await self.send_json(event.get("envelope") or {})

    @database_sync_to_async
    def _is_workspace_member(self, user_id, workspace_id) -> bool:
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceMembership,
        )

        ws = Workspace.objects.filter(id=workspace_id).only("id", "workspace_owner_id").first()
        if ws is None:
            return False
        if str(ws.workspace_owner_id) == str(user_id):
            return True
        return WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user_id=user_id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists()


class WorkspaceActivityConsumer(AsyncJsonWebsocketConsumer):
    """Per-workspace activity feed.

    URL: ``/ws/workspaces/<workspace_id>/activity/``

    Joins the workspace's activity group and pushes every event for
    every resource within the workspace. Frontend dashboard uses this
    to render the live "what's happening across this workspace" feed.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.workspace_id = self.scope["url_route"]["kwargs"]["workspace_id"]
        self.group_name = _workspace_group(self.workspace_id)

        if not await self._is_workspace_member(user.id, self.workspace_id):
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "workspace.stream.ready",
                "workspace_id": self.workspace_id,
            }
        )

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.exception(
                    "ws_workspace_disconnect_group_discard_failed group=%s",
                    self.group_name,
                )

    async def resource_event(self, event):
        await self.send_json(event.get("envelope") or {})

    @database_sync_to_async
    def _is_workspace_member(self, user_id, workspace_id) -> bool:
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceMembership,
        )

        ws = Workspace.objects.filter(id=workspace_id).only("id", "workspace_owner_id").first()
        if ws is None:
            return False
        if str(ws.workspace_owner_id) == str(user_id):
            return True
        return WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user_id=user_id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists()


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """A user's private real-time notification stream.

    URL: ``/ws/notifications/`` (no ids in the path — the stream spans
    every workspace the user belongs to).

    USER-SCOPED by construction: the group is derived from the
    authenticated ``scope["user"].id`` only — never from the URL or any
    client-supplied value — so a user can never subscribe to another
    user's notifications. Pushes the ``notification.event`` envelopes
    the ``RealtimeNotificationChannel`` publishes from the dispatcher
    funnel: ``notification.created`` (with the serialized row),
    ``notification.read`` / ``notification.all_read`` (multi-tab and
    multi-device read-state convergence), each carrying a fresh
    ``unread_count`` for the header badge.

    On connect it sends a ``notifications.ready`` message with the
    current unread count so the badge is correct immediately, without a
    separate REST round-trip.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.group_name = _user_notifications_group(str(user.id))
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        unread = None
        try:
            unread = await self._unread_count(user)
        except Exception:
            logger.exception("ws_notifications_ready_unread_failed user_id=%s", user.id)
        await self.send_json({"type": "notifications.ready", "unread_count": unread})

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.exception(
                    "ws_notifications_disconnect_group_discard_failed group=%s",
                    self.group_name,
                )

    async def notification_event(self, event):
        """Channel-layer handler — forwards ``notification.event``
        group messages to the connected client."""
        await self.send_json(event.get("envelope") or {})

    @database_sync_to_async
    def _unread_count(self, user) -> int:
        from components.notifications.infrastructure.adapters.cache import (
            get_unread_count,
        )

        return get_unread_count(user)


class SponsorFeedConsumer(AsyncJsonWebsocketConsumer):
    """A donor's private real-time transparency feed.

    URL: ``/ws/sponsor/feed/`` (no workspace in the path — a donor's feed
    spans every org they support).

    DONOR-SCOPED by construction: the group is derived from the
    authenticated ``scope["user"].id`` only — never from the URL or any
    client-supplied value — so a sponsor subscribes to *only their own*
    feed and never another donor's. Pushes the money events the
    sponsorship realtime handlers publish (donation received, sponsorship
    charged, funds spent on their behalf, balance updated).
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return

        self.group_name = _sponsor_feed_group(str(user.id))
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "sponsor.feed.ready"})

        # Backfill: replay recent persisted CONTENT items (recipient
        # updates + sent newsletters from the orgs this donor supports)
        # as the same ``resource.event`` envelopes the live signal
        # handlers publish. Without this the "Updates" feed is empty on
        # every fresh connection — live-only is the wrong UX for the
        # platform's headline transparency surface. Sent oldest-first so
        # a client that prepends ends up newest-on-top.
        try:
            envelopes = await self._backfill_envelopes(str(user.id), getattr(user, "email", "") or "")
            for envelope in envelopes:
                await self.send_json(envelope)
        except Exception:
            logger.exception("ws_sponsor_feed_backfill_failed user_id=%s", user.id)

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            try:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
            except Exception:
                logger.exception(
                    "ws_sponsor_feed_disconnect_group_discard_failed group=%s",
                    self.group_name,
                )

    async def resource_event(self, event):
        # Same channel-layer message type the realtime adapter sends
        # (``resource.event``) -> forward the envelope to the client.
        await self.send_json(event.get("envelope") or {})

    # How many of each content type to replay on connect. The frontend
    # feed keeps its 50 most recent events, so stay well under that.
    BACKFILL_UPDATES = 10
    BACKFILL_NEWSLETTERS = 5

    @database_sync_to_async
    def _backfill_envelopes(self, user_id: str, email: str) -> list[dict]:
        """Recent recipient updates + sent newsletters as feed envelopes.

        Audience resolution mirrors the live fan-out handlers
        (``recipient_update_feed_signals`` /
        ``sponsor_content_feed_handlers``): a donor supports a recipient
        via Sponsorship or Donation rows keyed by their email, and
        supports a workspace the same way. Envelope shape mirrors
        ``ChannelsRealtimeEventAdapter.publish_to_sponsor_feed`` exactly,
        with the row's own creation/send time as the timestamp.
        """
        # The sponsorship + content bounded contexts were dropped in the
        # auto-sec fork, so there is no sponsor content feed to
        # backfill. Returns empty until a security-domain feed replaces it.
        return []

        email = (email or "").strip().lower()
        if not email:
            return []

        sponsorships = Sponsorship.objects.filter(sponsor__email__iexact=email)
        donations = Donation.objects.filter(email__iexact=email)

        recipient_ids = {rid for rid in sponsorships.values_list("recipient_id", flat=True) if rid} | {
            rid for rid in donations.values_list("recipient_id", flat=True) if rid
        }
        workspace_ids = {wid for wid in sponsorships.values_list("workspace_id", flat=True) if wid} | {
            wid for wid in donations.values_list("workspace_id", flat=True) if wid
        }

        def _envelope(event_name, workspace_id, payload, when):
            return {
                "type": "resource.event",
                "resource_type": "sponsor_feed",
                "resource_id": str(user_id),
                "workspace_id": str(workspace_id) if workspace_id else "",
                "status": "",
                "progress_percent": 0,
                "event_name": event_name,
                "payload": payload,
                "timestamp": when.isoformat() if when else "",
            }

        items: list[tuple] = []

        for update in (
            RecipientUpdate.objects.select_related("recipient")
            .filter(recipient_id__in=recipient_ids)
            .order_by("-created_at")[: self.BACKFILL_UPDATES]
        ):
            recipient = update.recipient
            first = (getattr(recipient, "first_name", "") or "").strip()
            last = (getattr(recipient, "last_name", "") or "").strip()
            display = f"{first} {last[0] + '.' if last else ''}".strip() or "your recipient"
            body_text = getattr(update, "body", "") or ""
            items.append(
                (
                    update.created_at,
                    _envelope(
                        "recipient_update_posted",
                        update.workspace_id,
                        {
                            "update_id": str(update.id),
                            "recipient_name": display,
                            "title": (update.title or "").strip(),
                            "excerpt": " ".join(str(body_text).split())[:160],
                        },
                        update.created_at,
                    ),
                )
            )

        for newsletter in Newsletter.objects.filter(workspace_id__in=workspace_ids, status="sent").order_by(
            "-sent_at", "-created_at"
        )[: self.BACKFILL_NEWSLETTERS]:
            when = newsletter.sent_at or newsletter.created_at
            items.append(
                (
                    when,
                    _envelope(
                        "newsletter_sent",
                        newsletter.workspace_id,
                        {
                            "newsletter_id": str(newsletter.id),
                            "title": (newsletter.title or "").strip(),
                        },
                        when,
                    ),
                )
            )

        # Oldest first: the client prepends each event, so replaying in
        # chronological order leaves the newest item at the top.
        items.sort(key=lambda pair: pair[0])
        return [envelope for _when, envelope in items]
