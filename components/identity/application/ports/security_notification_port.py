"""Port for dispatching security-related notifications.

The application layer calls this port; infrastructure provides the
adapter that uses the notifications app or external services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class SecurityNotificationPort(ABC):
    """Secondary/driven port for security event notifications."""

    @abstractmethod
    def notify_security_event(
        self,
        *,
        actor_id: UUID | None,
        user_id: UUID,
        verb: str,
        event_code: str,
        metadata: dict | None,
    ) -> None:
        """Dispatch a security event notification to the user."""
        ...
