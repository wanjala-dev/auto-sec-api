"""Port for notification count caching.

Any cache backend (Redis, Memcached, ElastiCache, …) implements this
contract so the application layer never couples to a specific cache SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class NotificationCachePort(ABC):
    """Secondary/driven port for notification count caching."""

    @abstractmethod
    def get_unread_count(self, user_id: int, workspace_id: Optional[int] = None) -> Optional[int]:
        """Return cached unread count, or None if not cached."""
        ...

    @abstractmethod
    def set_unread_count(self, user_id: int, count: int, workspace_id: Optional[int] = None) -> None:
        """Cache the unread count."""
        ...

    @abstractmethod
    def invalidate(self, user_id: int, workspace_id: Optional[int] = None) -> None:
        """Invalidate cached count for a user (optionally scoped to workspace)."""
        ...
