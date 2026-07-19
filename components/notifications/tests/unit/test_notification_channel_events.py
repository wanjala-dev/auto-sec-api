"""Unit coverage for the realtime read-state publishing (T1-S2).

Framework-free: fake port + fake repo, no DB. Asserts the mark-read use
cases publish the right NotificationEvent exactly when state changed —
the contract the frontend's multi-tab badge convergence depends on.
"""

from __future__ import annotations

from uuid import uuid4

from components.notifications.application.commands.mark_notifications_command import (
    MarkAllNotificationsReadCommand,
    MarkNotificationReadCommand,
)
from components.notifications.application.ports.notification_channel_port import (
    NOTIFICATION_ALL_READ,
    NOTIFICATION_READ,
    NotificationChannelPort,
    NotificationEvent,
)
from components.notifications.application.ports.notification_repository_port import (
    MarkReadOutcome,
)
from components.notifications.application.use_cases.mark_all_notifications_read_use_case import (
    MarkAllNotificationsReadUseCase,
)
from components.notifications.application.use_cases.mark_notification_read_use_case import (
    MarkNotificationReadUseCase,
)


class FakeChannel(NotificationChannelPort):
    def __init__(self):
        self.delivered: list[NotificationEvent] = []

    def deliver(self, event: NotificationEvent) -> None:
        self.delivered.append(event)


class FakeRepo:
    def __init__(self, *, outcome=None, mark_all_count=0):
        self._outcome = outcome or MarkReadOutcome(changed=False)
        self._mark_all_count = mark_all_count

    def mark_read(self, notification_id):
        return self._outcome

    def mark_all_read(self, user_id, *, workspace_id=None):
        return self._mark_all_count


class TestMarkReadPublishes:
    def test_publishes_read_event_when_changed(self):
        recipient_id = str(uuid4())
        channel = FakeChannel()
        use_case = MarkNotificationReadUseCase(
            notification_repo=FakeRepo(
                outcome=MarkReadOutcome(changed=True, recipient_id=recipient_id, workspace_id=None)
            ),
            notification_channel=channel,
        )

        result = use_case.execute(MarkNotificationReadCommand(notification_id=42, user_id=uuid4()))

        assert result.success is True
        assert len(channel.delivered) == 1
        event = channel.delivered[0]
        assert event.event_name == NOTIFICATION_READ
        assert event.recipient_id == recipient_id
        assert event.notification_id == "42"

    def test_no_publish_when_already_read(self):
        channel = FakeChannel()
        use_case = MarkNotificationReadUseCase(
            notification_repo=FakeRepo(outcome=MarkReadOutcome(changed=False, recipient_id=str(uuid4()))),
            notification_channel=channel,
        )

        result = use_case.execute(MarkNotificationReadCommand(notification_id=42, user_id=uuid4()))

        assert result.success is False
        assert channel.delivered == []

    def test_channel_is_optional(self):
        use_case = MarkNotificationReadUseCase(
            notification_repo=FakeRepo(outcome=MarkReadOutcome(changed=True, recipient_id=str(uuid4()))),
        )
        result = use_case.execute(MarkNotificationReadCommand(notification_id=42, user_id=uuid4()))
        assert result.success is True


class TestMarkAllReadPublishes:
    def test_publishes_all_read_event_when_rows_changed(self):
        user_id = uuid4()
        channel = FakeChannel()
        use_case = MarkAllNotificationsReadUseCase(
            notification_repo=FakeRepo(mark_all_count=3),
            notification_channel=channel,
        )

        result = use_case.execute(MarkAllNotificationsReadCommand(user_id=user_id, workspace_id=None))

        assert result.updated_count == 3
        assert len(channel.delivered) == 1
        event = channel.delivered[0]
        assert event.event_name == NOTIFICATION_ALL_READ
        assert event.recipient_id == str(user_id)

    def test_no_publish_when_nothing_was_unread(self):
        channel = FakeChannel()
        use_case = MarkAllNotificationsReadUseCase(
            notification_repo=FakeRepo(mark_all_count=0),
            notification_channel=channel,
        )

        result = use_case.execute(MarkAllNotificationsReadCommand(user_id=uuid4(), workspace_id=None))

        assert result.updated_count == 0
        assert channel.delivered == []
