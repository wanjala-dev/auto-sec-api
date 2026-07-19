"""Port for workspace data caching.

Any cache backend (Redis, Memcached, ElastiCache, …) implements this
contract so the workspace layer never couples to a specific cache SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class WorkspaceCachePort(ABC):
    """Secondary/driven port for workspace response caching."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Return cached value, or None if not cached."""
        ...

    @abstractmethod
    def set(self, key: str, value: Any, timeout: int = 300) -> None:
        """Cache a value."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a cached value."""
        ...
