"""ORM adapter implementing NotificationRepositoryPort.

This is the infrastructure boundary — Django ORM lives here, not in domain/application.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from components.notifications.application.ports.notification_repository_port import (
    NotificationRepositoryPort,
)
from components.notifications.domain.entities.notification_entity import (
    NotificationEntity,
)
from components.notifications.domain.value_objects.notification_filter import (
    NotificationFilter,
)
from components.notifications.mappers.db.notification_mapper import (
    to_notification_entity,
)


class OrmNotificationRepository(NotificationRepositoryPort):
    """Concrete adapter backed by Django ORM."""

    def list_notifications(self, criteria: NotificationFilter) -> list[NotificationEntity]:
        from django.utils import timezone as tz

        from infrastructure.persistence.notifications.models import Notification

        qs = Notification.objects.filter(recipient_id=criteria.user_id)

        if criteria.is_read is not None:
            qs = qs.filter(is_read=criteria.is_read)
        if criteria.notification_type is not None:
            qs = qs.filter(notification_type=criteria.notification_type)
        if criteria.workspace_id is not None:
            qs = qs.filter(workspace_id=criteria.workspace_id)
        if criteria.created_after is not None:
            qs = qs.filter(created_at__gte=criteria.created_after)
        if criteria.created_before is not None:
            qs = qs.filter(created_at__lte=criteria.created_before)

        # Period-based filter
        if criteria.period:
            now = tz.now()
            if criteria.period == "today":
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                qs = qs.filter(created_at__gte=start)
            elif criteria.period == "last_7_days":
                qs = qs.filter(created_at__gte=now - timedelta(days=7))
            elif criteria.period == "last_30_days":
                qs = qs.filter(created_at__gte=now - timedelta(days=30))

        qs = qs.select_related(
            "actor",
            "actor__profile",
            "recipient",
            "recipient__profile",
            "content_type",
            "workspace",
        ).order_by("-created_at")

        return [to_notification_entity(n) for n in qs]

    def find_by_id(self, notification_id: int) -> NotificationEntity | None:
        from infrastructure.persistence.notifications.models import Notification

        try:
            obj = Notification.objects.get(id=notification_id)
            return to_notification_entity(obj)
        except Notification.DoesNotExist:
            return None

    def mark_read(self, notification_id: int):
        from components.notifications.application.ports.notification_repository_port import (
            MarkReadOutcome,
        )
        from infrastructure.persistence.notifications.models import Notification

        try:
            notification = Notification.objects.get(id=notification_id)
        except Notification.DoesNotExist:
            return MarkReadOutcome(changed=False)

        outcome = MarkReadOutcome(
            changed=not notification.is_read,
            recipient_id=str(notification.recipient_id),
            workspace_id=str(notification.workspace_id) if notification.workspace_id else None,
        )
        if outcome.changed:
            notification.mark_as_read()
        return outcome

    def mark_all_read(self, user_id: UUID, *, workspace_id: UUID | None = None) -> int:
        from django.utils import timezone as tz

        from components.notifications.infrastructure.adapters.cache import invalidate_unread_count_cache
        from infrastructure.persistence.notifications.models import Notification

        qs = Notification.objects.filter(recipient_id=user_id, is_read=False)
        if workspace_id is not None:
            qs = qs.filter(workspace_id=workspace_id)

        updated = qs.update(is_read=True, read_at=tz.now())
        invalidate_unread_count_cache(user_id, workspace_id)
        return updated

    def unread_count(self, user_id: UUID, *, workspace_id: UUID | None = None) -> int:
        from components.notifications.infrastructure.adapters.cache import get_unread_count
        from infrastructure.persistence.users.models import CustomUser

        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return 0
        return get_unread_count(user, workspace_id)

    # ── QuerySet methods (for DRF pagination on read path) ───────────────

    def get_notifications_queryset(self, user_id):
        """Return base queryset for a user's notifications (DRF integration)."""
        from infrastructure.persistence.notifications.models import Notification

        return (
            Notification.objects.for_user_by_id(user_id)
            if hasattr(Notification.objects, "for_user_by_id")
            else Notification.objects.filter(recipient_id=user_id)
        ).select_related(
            "actor",
            "actor__profile",
            "recipient",
            "recipient__profile",
            "content_type",
            "workspace",
        )

    def get_workspace_preferences_queryset(self, user_id):
        """Return workspace notification preferences for a user."""
        from infrastructure.persistence.notifications.models import WorkspaceNotificationPreference

        return WorkspaceNotificationPreference.objects.filter(
            user_id=user_id,
        ).select_related("workspace")

    def get_ai_preferences_queryset(self, user_id):
        """Return AI notification preferences for a user."""
        from infrastructure.persistence.notifications.models import AINotificationPreference

        return AINotificationPreference.objects.filter(
            user_id=user_id,
        ).select_related("workspace")

    def get_user_preference(self, user_id):
        """Get or create user notification preference."""
        from infrastructure.persistence.notifications.userpreferences.models import UserPreference
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.get(id=user_id)
        preference, _ = UserPreference.objects.get_or_create(user=user)
        return preference

    def list_user_preferences(self):
        """List all user preferences."""
        from infrastructure.persistence.notifications.userpreferences.models import UserPreference

        return UserPreference.objects.all()

    def delete_user_preference(self, user_id):
        """Delete user notification preference."""
        from infrastructure.persistence.notifications.userpreferences.models import UserPreference

        preference = UserPreference.objects.get(user_id=user_id)
        preference.delete()
