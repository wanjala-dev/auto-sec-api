from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from components.notifications.infrastructure.adapters.notification_service import (
    NotificationDispatcher,
)
from components.payments.application.ports.notification_dispatch_port import (
    NotificationDispatchPort,
)


class NotificationDispatchAdapter(NotificationDispatchPort):
    """Adapter that wraps the notifications context's NotificationDispatcher.

    Encapsulates the cross-context dependency on the notifications infrastructure,
    allowing the payments context to depend on a local port instead of directly
    importing from the notifications infrastructure.
    """

    def __init__(self, dispatcher: NotificationDispatcher | None = None):
        """Initialize with optional dependency injection for testing.

        Args:
            dispatcher: Optional NotificationDispatcher instance. If not provided,
                       a new instance will be created with default preferences service.
        """
        self._dispatcher = dispatcher or NotificationDispatcher()

    def dispatch_notification(
        self,
        *,
        actor: Any,
        workspace: Any,
        verb: str,
        notification_type: str,
        recipients: Sequence[Any],
        metadata: dict | None = None,
        target: Any = None,
        ai_channel: str | None = None,
        logo_url: str | None = None,
    ) -> None:
        """Dispatch a notification to specified recipients.

        Delegates to the wrapped NotificationDispatcher instance, translating
        the port interface to the dispatcher's dispatch method signature.

        Args:
            actor: The user who initiated the action
            workspace: The workspace context for the notification
            verb: The notification message/description
            notification_type: The type of notification (e.g., SYSTEM, AI_EVENT)
            recipients: List of users to receive the notification
            metadata: Optional metadata to attach to the notification
            target: Optional target entity for the notification
            ai_channel: Optional AI channel identifier
            logo_url: Optional URL for notification logo

        Returns:
            None
        """
        self._dispatcher.dispatch(
            actor=actor,
            workspace=workspace,
            verb=verb,
            notification_type=notification_type,
            recipients=recipients,
            metadata=metadata,
            target=target,
            ai_channel=ai_channel,
            logo_url=logo_url,
        )
