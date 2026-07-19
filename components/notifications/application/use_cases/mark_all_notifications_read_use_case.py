"""Mark-all-notifications-read use case — framework-free business orchestration."""

from __future__ import annotations

from components.notifications.application.commands.mark_notifications_command import (
    MarkAllNotificationsReadCommand,
    MarkAllNotificationsReadResult,
)
from components.notifications.application.ports.notification_channel_port import (
    NOTIFICATION_ALL_READ,
    NotificationChannelPort,
    NotificationEvent,
)
from components.notifications.application.ports.notification_repository_port import (
    NotificationRepositoryPort,
)


class MarkAllNotificationsReadUseCase:
    """Mark all unread notifications for a user as read.

    Publishes a ``notification.all_read`` event to the user's realtime
    stream when anything changed, so other open tabs/devices zero their
    badge and flip visible rows without polling. The channel is optional
    and loss-tolerant by contract.
    """

    def __init__(
        self,
        *,
        notification_repo: NotificationRepositoryPort,
        notification_channel: NotificationChannelPort | None = None,
    ) -> None:
        self._repo = notification_repo
        self._channel = notification_channel

    def execute(self, command: MarkAllNotificationsReadCommand) -> MarkAllNotificationsReadResult:
        count = self._repo.mark_all_read(
            command.user_id,
            workspace_id=command.workspace_id,
        )
        if count and self._channel is not None:
            self._channel.deliver(
                NotificationEvent(
                    event_name=NOTIFICATION_ALL_READ,
                    recipient_id=str(command.user_id),
                    workspace_id=str(command.workspace_id) if command.workspace_id else None,
                )
            )
        return MarkAllNotificationsReadResult(updated_count=count)
