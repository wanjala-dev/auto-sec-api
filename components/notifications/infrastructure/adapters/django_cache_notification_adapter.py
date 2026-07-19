"""Django cache adapter implementing NotificationCachePort."""

from __future__ import annotations

from typing import Optional

from components.notifications.application.ports.notification_cache_port import NotificationCachePort


GLOBAL_TOKEN = "__global__"
DEFAULT_TIMEOUT = 60


class DjangoCacheNotificationAdapter(NotificationCachePort):
    """Concrete adapter backed by Django cache framework."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self._timeout = timeout

    def get_unread_count(self, user_id: int, workspace_id: Optional[int] = None) -> Optional[int]:
        from django.core.cache import cache

        key = self._key(user_id, workspace_id)
        return cache.get(key)

    def set_unread_count(self, user_id: int, count: int, workspace_id: Optional[int] = None) -> None:
        from django.core.cache import cache

        key = self._key(user_id, workspace_id)
        cache.set(key, count, self._timeout)

    def invalidate(self, user_id: int, workspace_id: Optional[int] = None) -> None:
        from django.core.cache import cache

        cache.delete(self._key(user_id, None))
        if workspace_id is not None:
            cache.delete(self._key(user_id, workspace_id))

    @staticmethod
    def _key(user_id: int, workspace_id: Optional[int]) -> str:
        token = str(workspace_id) if workspace_id is not None else GLOBAL_TOKEN
        return f"notifications:unread:{user_id}:{token}"
