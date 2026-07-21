from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import models

from components.notifications.infrastructure.adapters.platform_middleware import get_current_actor
from infrastructure.persistence.notifications.models import (
    AINotificationPreference,
    Notification,
    WorkspaceNotificationPreference,
)

User = get_user_model()


class NotificationRecipientBuilder:
    """Collect recipients while preventing duplicates."""

    def __init__(self):
        self._users: OrderedDict[str, User] = OrderedDict()

    def add(self, user) -> None:
        if not user or not getattr(user, "pk", None):
            return
        key = str(user.pk)
        if key not in self._users:
            self._users[key] = user

    def add_queryset(self, queryset) -> None:
        for user in queryset:
            self.add(user)

    def add_iterable(self, iterable: Iterable) -> None:
        for user in iterable:
            self.add(user)

    def build(self) -> list[User]:
        return list(self._users.values())


def workspace_recipient_builder(
    workspace,
    *,
    include_owner: bool = True,
    include_followers: bool = True,
    include_team_members: bool = True,
    include_donors: bool = False,
) -> NotificationRecipientBuilder:
    builder = NotificationRecipientBuilder()
    if not workspace:
        return builder

    if include_owner:
        builder.add(getattr(workspace, "workspace_owner", None))
    if include_followers:
        builder.add_queryset(workspace.followers.all())
    if include_team_members:
        workspace_id = getattr(workspace, "id", workspace)
        builder.add_queryset(User.objects.filter(team_memberships__team__workspace_id=workspace_id).distinct())
    if include_donors:
        builder.add_queryset(users_for_donations(workspace=workspace))
    return builder


def users_for_donations(*, workspace=None, donations=None):
    Donation = apps.get_model("donations", "Donation")
    queryset = donations
    if queryset is None:
        if workspace is None:
            return User.objects.none()
        queryset = Donation.objects.filter(workspace=workspace)

    emails = {email for email in queryset.exclude(email__isnull=True).exclude(email="").values_list("email", flat=True)}
    if not emails:
        return User.objects.none()
    return User.objects.filter(email__in=emails)


def sanitize_metadata(value):
    if isinstance(value, dict):
        return {str(key): sanitize_metadata(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_metadata(val) for val in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, models.Model):
        if value.pk:
            return str(value.pk)
        return str(value)
    return value


def resolve_actor(instance):
    actor = get_current_actor()
    if actor:
        return actor
    return guess_actor(instance)


def guess_actor(instance):
    for attr in (
        "updated_by",
        "modified_by",
        "user",
        "owner",
        "created_by",
        "author",
        "workspace_owner",
        "userId",
    ):
        user = getattr(instance, attr, None)
        if isinstance(user, User):
            return user
    return None


PREFERENCE_CACHE_TTL = 300  # 5 minutes


def _pref_cache_key(user_id, workspace_id, notification_type, ai_channel=None):
    ws = workspace_id or "__global__"
    nt = notification_type or "__any__"
    ch = ai_channel or "__none__"
    return f"notif_pref:{user_id}:{ws}:{nt}:{ch}"


def _channels_cache_key(user_id):
    return f"notif_channels:{user_id}"


def invalidate_channel_cache(user_id):
    """Flush the cached per-channel delivery decision for a user.

    Called from the user-preference endpoints so flipping
    ``push_notifications`` / ``email_notifications`` takes effect
    immediately instead of after the TTL.
    """
    from django.core.cache import cache

    cache.delete(_channels_cache_key(user_id))


def channels_for(user):
    """Return the delivery channels enabled for ``user`` (T1-S5 gate).

    Reads the revived ``UserPreference.push_notifications`` /
    ``email_notifications`` booleans and applies
    :func:`resolve_enabled_channels` — realtime is always on; web_push and
    email are opt-in. Decisions are cached per user for
    ``PREFERENCE_CACHE_TTL`` seconds (same pattern as the recipient
    preference gate above) so broadcast dispatches don't re-query per row.
    """
    from django.core.cache import cache

    from components.notifications.domain.policies.delivery_channel_policy import (
        resolve_enabled_channels,
    )

    user_id = getattr(user, "pk", None) or getattr(user, "id", None) or user
    key = _channels_cache_key(user_id)
    cached = cache.get(key)
    if cached is not None:
        return tuple(cached)

    UserPreference = apps.get_model("userpreferences", "UserPreference")
    pref = UserPreference.objects.filter(user_id=user_id).only("push_notifications", "email_notifications").first()
    channels = resolve_enabled_channels(
        push_enabled=bool(pref and pref.push_notifications),
        email_enabled=bool(pref and pref.email_notifications),
    )
    values = [channel.value for channel in channels]
    cache.set(key, values, PREFERENCE_CACHE_TTL)
    return tuple(values)


def invalidate_preference_cache(user_id, workspace_id=None):
    """Flush cached preference decisions for a user+workspace pair.

    Called from preference CRUD endpoints so changes take effect immediately.
    Also drops the per-channel delivery decision — it derives from the same
    ``UserPreference`` row.
    """
    from django.core.cache import cache

    cache.delete(_channels_cache_key(user_id))

    # Wildcard invalidation isn't supported by all cache backends, so
    # we delete patterns for the known notification types. This is
    # cheaper than a full cache flush and covers all practical cases.
    ws = workspace_id or "__global__"
    for nt in list(Notification.NotificationType.values) + ["__any__"]:
        for ch in [
            "__none__",
            AINotificationPreference.CHANNEL_GENERAL,
            AINotificationPreference.CHANNEL_TEAMMATE_STATUS,
            AINotificationPreference.CHANNEL_ACTION_CREATED,
            AINotificationPreference.CHANNEL_ACTION_AUTO_EXECUTED,
            AINotificationPreference.CHANNEL_ACTION_ERROR,
            AINotificationPreference.CHANNEL_REPORT_GENERATED,
        ]:
            cache.delete(f"notif_pref:{user_id}:{ws}:{nt}:{ch}")


class NotificationPreferenceService:
    """Evaluate recipient- and workspace-level notification toggles.

    Results are cached per user+workspace+type for PREFERENCE_CACHE_TTL
    seconds to avoid repeated DB queries during broadcast-style dispatches.
    """

    def __init__(self):
        self._user_pref_model = None

    @property
    def user_pref_model(self):
        if self._user_pref_model is None:
            self._user_pref_model = apps.get_model("userpreferences", "UserPreference")
        return self._user_pref_model

    def filter_recipients(
        self,
        recipients: Sequence[User],
        *,
        workspace=None,
        notification_type: str | None = None,
        ai_channel: str | None = None,
    ) -> list[User]:
        from django.core.cache import cache

        valid = [user for user in recipients if user and getattr(user, "pk", None)]
        if not valid:
            return []

        workspace_id = getattr(workspace, "pk", None) or getattr(workspace, "id", None)

        # Check cache first — users whose decision is already known skip DB.
        uncached_users = []
        cached_allowed = []
        for user in valid:
            key = _pref_cache_key(user.pk, workspace_id, notification_type, ai_channel)
            cached = cache.get(key)
            if cached is True:
                cached_allowed.append(user)
            elif cached is False:
                pass  # explicitly blocked, skip
            else:
                uncached_users.append(user)

        if not uncached_users:
            return cached_allowed

        # Query preferences for uncached users only.
        user_ids = [user.pk for user in uncached_users]
        user_pref_map = {
            pref.user_id: pref.notifications_enabled
            for pref in self.user_pref_model.objects.filter(user_id__in=user_ids)
        }
        workspace_pref_map = {}
        if workspace:
            workspace_pref_map = {
                pref.user_id: pref.is_enabled
                for pref in WorkspaceNotificationPreference.objects.filter(workspace=workspace, user_id__in=user_ids)
            }
        workspace_enabled = getattr(workspace, "notifications_enabled", True)

        ai_prefs = {}
        if notification_type == Notification.NotificationType.AI_EVENT and workspace:
            ai_prefs = {
                (pref.user_id, pref.channel): pref.is_enabled
                for pref in AINotificationPreference.objects.filter(workspace=workspace, user_id__in=user_ids)
            }
            ai_channel = ai_channel or AINotificationPreference.CHANNEL_GENERAL

        filtered = list(cached_allowed)
        for user in uncached_users:
            allowed = True
            if (
                not user_pref_map.get(user.pk, True)
                or (workspace and not workspace_enabled)
                or (workspace and not workspace_pref_map.get(user.pk, True))
            ):
                allowed = False
            elif notification_type == Notification.NotificationType.AI_EVENT:
                channel_allowed = ai_prefs.get((user.pk, ai_channel))
                if channel_allowed is None:
                    channel_allowed = ai_prefs.get((user.pk, AINotificationPreference.CHANNEL_GENERAL))
                if channel_allowed is False:
                    allowed = False

            # Cache the decision (True or False).
            key = _pref_cache_key(user.pk, workspace_id, notification_type, ai_channel)
            cache.set(key, allowed, PREFERENCE_CACHE_TTL)

            if allowed:
                filtered.append(user)
        return filtered


class NotificationDispatcher:
    """High-level helper wrapping ``create_notification``."""

    def __init__(self, preference_service: NotificationPreferenceService | None = None):
        self.preference_service = preference_service or NotificationPreferenceService()

    def dispatch(
        self,
        *,
        actor,
        workspace,
        verb: str,
        notification_type: str,
        recipients: Sequence[User],
        metadata: dict | None = None,
        target=None,
        ai_channel: str | None = None,
        logo_url: str | None = None,
        allow_self_notify: bool = False,
        link: str | None = None,
    ):
        """Fan a notification out to ``recipients`` through the canonical funnel.

        This is the ONLY sanctioned way to create ``Notification`` rows from
        other bounded contexts (enforced by
        ``tests/architecture/test_notification_dispatch_rules.py``). It applies
        preference filtering, then enqueues one Celery task per recipient
        post-commit.

        ``allow_self_notify`` — pass True for system-generated events where the
        recipient legitimately stands in as the actor (workflow run finished,
        report ready, security alert, bank-feed lifecycle, import completed).
        Default False preserves the social-action semantic (no "you liked your
        own post" noise).

        ``link`` — optional explicit RELATIVE frontend path for this
        notification. When omitted, ``dispatch_notification_async`` resolves
        one via ``link_resolver.resolve_link()`` (after target rehydration)
        and writes it into ``metadata["link"]`` so the in-app row, the WS
        envelope, and push payloads all carry the same destination. An
        explicit ``link`` always wins over the resolver.
        """
        if actor is None or not recipients:
            return
        allowed = self.preference_service.filter_recipients(
            recipients,
            workspace=workspace,
            notification_type=notification_type,
            ai_channel=ai_channel,
        )
        if not allowed:
            return

        metadata = sanitize_metadata(metadata or {})
        if ai_channel and "ai_channel" not in metadata:
            metadata = {**metadata, "ai_channel": ai_channel}

        # Dispatch asynchronously via Celery to avoid blocking the
        # request when notifying many recipients (e.g. team broadcasts).
        from django.db import transaction as db_transaction

        from components.notifications.workers.tasks import dispatch_notification_async

        actor_id = getattr(actor, "pk", None) or getattr(actor, "id", None)
        workspace_id = str(getattr(workspace, "pk", None) or getattr(workspace, "id", "")) if workspace else None

        # The GenericFK target can't cross the Celery boundary as an object —
        # serialize a (app_label, model, pk) reference and rehydrate in the
        # task. Before this existed, dispatch() silently DROPPED target on the
        # async path and every migrated call site lost its deep-link anchor.
        target_ref = None
        if target is not None and getattr(target, "pk", None):
            target_ref = [target._meta.app_label, target._meta.model_name, str(target.pk)]

        for recipient in allowed:
            recipient_id = getattr(recipient, "pk", None) or getattr(recipient, "id", None)
            kwargs = dict(
                recipient_id=recipient_id,
                actor_id=actor_id,
                verb=verb,
                notification_type=notification_type,
                workspace_id=workspace_id,
                metadata=metadata,
                logo_url=logo_url,
                target_ref=target_ref,
                allow_self_notify=allow_self_notify,
                link=link,
            )
            db_transaction.on_commit(lambda kw=kwargs: dispatch_notification_async.apply_async(kwargs=kw))
