"""Port for authentication audit event persistence.

The application layer calls this port to record auth events;
infrastructure provides the ORM adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import RequestContext


class AuthAuditPort(ABC):
    """Secondary/driven port for auth audit event recording."""

    @abstractmethod
    def record_event(
        self,
        *,
        event_code: str,
        user_id: UUID | None,
        email: str,
        success: bool,
        context: RequestContext,
        metadata: dict | None,
    ) -> None:
        """Persist an auth/2FA audit event."""
        ...
