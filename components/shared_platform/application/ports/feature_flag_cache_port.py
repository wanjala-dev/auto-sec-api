"""Port for feature flag evaluation caching.

Any cache backend (Redis, Memcached, ElastiCache, …) implements this
contract so feature flag logic never couples to a specific cache SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class FeatureFlagCachePort(ABC):
    """Secondary/driven port for feature flag caching."""

    @abstractmethod
    def get_version(self) -> int:
        """Return the current feature flag version counter."""
        ...

    @abstractmethod
    def bump_version(self) -> int:
        """Increment the version counter and return the new value."""
        ...

    @abstractmethod
    def get_evaluation(self, key: str) -> Optional[dict]:
        """Return cached flag evaluation, or None if not cached."""
        ...

    @abstractmethod
    def set_evaluation(self, key: str, value: dict, timeout: int = 300) -> None:
        """Cache a flag evaluation result."""
        ...
