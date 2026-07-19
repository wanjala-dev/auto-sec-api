from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol


class NotificationDispatchPort(Protocol):
    """Port for dispatching notifications within the payments context.

    Abstracts notification infrastructure from the payments domain, allowing
    the payments context to request notifications without directly depending
    on the notifications context's infrastructure.
    """

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
        ...
