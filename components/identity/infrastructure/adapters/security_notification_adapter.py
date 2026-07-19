"""Notification adapter implementing SecurityNotificationPort.

Delegates to the existing notifications infrastructure.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.security_notification_port import SecurityNotificationPort


class DjangoSecurityNotificationAdapter(SecurityNotificationPort):
    """Concrete adapter backed by Django notifications app."""

    def notify_security_event(
        self,
        *,
        actor_id: UUID | None,
        user_id: UUID,
        verb: str,
        event_code: str,
        metadata: dict | None,
    ) -> None:
        from components.identity.infrastructure.adapters.security import record_security_event

        record_security_event(
            actor_id=actor_id,
            user_id=user_id,
            verb=verb,
            event_code=event_code,
            metadata=metadata,
        )
