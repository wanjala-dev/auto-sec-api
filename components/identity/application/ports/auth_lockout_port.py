"""Port for authentication lockout state persistence.

The application layer calls this port; infrastructure provides the concrete
adapter (e.g., Django cache, Redis).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AuthLockoutPort(ABC):
    """Secondary/driven port for lockout state storage."""

    @abstractmethod
    def get_failure_count(self, scope: str, identifier: str) -> int:
        """Return current failure count for the given scope/identifier."""
        ...

    @abstractmethod
    def is_locked(self, scope: str, identifier: str) -> tuple[bool, int]:
        """Return (is_locked, remaining_seconds)."""
        ...

    @abstractmethod
    def increment_failure(self, scope: str, identifier: str) -> int:
        """Increment failure count and return new count."""
        ...

    @abstractmethod
    def activate_lockout(self, scope: str, identifier: str, window_minutes: int) -> None:
        """Activate lockout for the given window."""
        ...

    @abstractmethod
    def clear(self, scope: str, identifier: str) -> None:
        """Clear lockout state."""
        ...
