"""Application service for the notifications bounded context.

Orchestration only – delegates to use cases via NotificationsProvider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from components.notifications.application.providers.notifications_provider import NotificationsProvider


@dataclass
class NotificationsService:
    """Application service for the notifications bounded context.

    Orchestration only – delegates to use cases for business logic.
    """

    provider: NotificationsProvider = field(default_factory=NotificationsProvider)

    def mark_notification_read(self, command) -> Any:
        """Mark a notification as read."""
        use_case = self.provider.build_mark_notification_read_use_case()
        return use_case.execute(command)

    def mark_all_notifications_read(self, command) -> Any:
        """Mark all notifications as read."""
        use_case = self.provider.build_mark_all_notifications_read_use_case()
        return use_case.execute(command)

    # ── Repository read queries ──

    def get_unread_count(self, user_id, workspace_id: UUID | None = None) -> int:
        """Get unread notification count for a user."""
        repo = self.provider.build_notification_repository()
        return repo.unread_count(user_id, workspace_id=workspace_id)

    def get_notifications_queryset(self, user_id):
        """Return base queryset for DRF pagination integration."""
        repo = self.provider.build_notification_repository()
        return repo.get_notifications_queryset(user_id)

    def get_workspace_preferences_queryset(self, user_id):
        """Return workspace notification preferences queryset."""
        repo = self.provider.build_notification_repository()
        return repo.get_workspace_preferences_queryset(user_id)

    def get_ai_preferences_queryset(self, user_id):
        """Return AI notification preferences queryset."""
        repo = self.provider.build_notification_repository()
        return repo.get_ai_preferences_queryset(user_id)

    def find_user_by_id(self, user_id):
        """Resolve a user id to a user, or None. Never raises."""
        repo = self.provider.build_notification_repository()
        return repo.find_user_by_id(user_id)

    def get_user_preference(self, user):
        """Get or create the preference row owned by ``user`` (an instance)."""
        repo = self.provider.build_notification_repository()
        return repo.get_user_preference(user)

    def list_user_preferences(self, for_user=None):
        """Preference rows — every row when ``for_user`` is None, else theirs."""
        repo = self.provider.build_notification_repository()
        return repo.list_user_preferences(for_user=for_user)

    def delete_user_preference(self, user):
        """Delete ``user``'s preference row. Returns the number removed."""
        repo = self.provider.build_notification_repository()
        return repo.delete_user_preference(user)
