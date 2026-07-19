"""Mark-notification-read use case — framework-free business orchestration."""

from __future__ import annotations

from components.notifications.application.commands.mark_notifications_command import (
    MarkNotificationReadCommand,
    MarkNotificationReadResult,
)
from components.notifications.application.ports.notification_channel_port import (
    NOTIFICATION_READ,
    NotificationChannelPort,
    NotificationEvent,
)
from components.notifications.application.ports.notification_repository_port import (
    NotificationRepositoryPort,
)


class MarkNotificationReadUseCase:
    """Mark a single notification as read.

    Publishes a ``notification.read`` event to the recipient's realtime
    stream when the row actually flipped, so other open tabs/devices
    converge their badge and read state without polling. The channel is
    optional (None in contexts without realtime wiring) and loss-tolerant
    by contract — publishing never affects the result.
    """

    def __init__(
        self,
        *,
        notification_repo: NotificationRepositoryPort,
        notification_channel: NotificationChannelPort | None = None,
    ) -> None:
        self._repo = notification_repo
        self._channel = notification_channel

    def execute(self, command: MarkNotificationReadCommand) -> MarkNotificationReadResult:
        outcome = self._repo.mark_read(command.notification_id)
        if outcome.changed and self._channel is not None and outcome.recipient_id:
            self._channel.deliver(
                NotificationEvent(
                    event_name=NOTIFICATION_READ,
                    recipient_id=outcome.recipient_id,
                    notification_id=str(command.notification_id),
                    workspace_id=outcome.workspace_id,
                )
            )
        return MarkNotificationReadResult(
            success=outcome.changed,
            notification_id=command.notification_id,
        )
