"""Unit tests for notification use cases."""

from __future__ import annotations

from unittest.mock import Mock, MagicMock
from uuid import uuid4

import unittest

from components.notifications.application.ports.notification_repository_port import (
    MarkReadOutcome,
)
from components.notifications.application.commands.mark_notifications_command import (
    MarkAllNotificationsReadCommand,
    MarkNotificationReadCommand,
)
from components.notifications.application.use_cases.mark_all_notifications_read_use_case import (
    MarkAllNotificationsReadUseCase,
)
from components.notifications.application.use_cases.mark_notification_read_use_case import (
    MarkNotificationReadUseCase,
)


class TestMarkNotificationReadUseCase(unittest.TestCase):
    """Tests for MarkNotificationReadUseCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_repo = Mock()
        self.use_case = MarkNotificationReadUseCase(notification_repo=self.mock_repo)
        self.user_id = uuid4()

    def test_use_case_initialization(self):
        """Verify use case initializes with repository."""
        assert self.use_case._repo == self.mock_repo

    def test_execute_notification_marked_as_read(self):
        """Execute marks a notification as read and returns success."""
        # Arrange
        notification_id = 42
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=True, recipient_id=str(self.user_id))
        command = MarkNotificationReadCommand(
            notification_id=notification_id,
            user_id=self.user_id,
        )

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.success is True
        assert result.notification_id == notification_id
        self.mock_repo.mark_read.assert_called_once_with(notification_id)

    def test_execute_notification_already_read(self):
        """Execute returns False when notification already read."""
        # Arrange
        notification_id = 42
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=False)
        command = MarkNotificationReadCommand(
            notification_id=notification_id,
            user_id=self.user_id,
        )

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.success is False
        assert result.notification_id == notification_id

    def test_execute_notification_not_found(self):
        """Execute returns False when notification not found."""
        # Arrange
        notification_id = 999
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=False)
        command = MarkNotificationReadCommand(
            notification_id=notification_id,
            user_id=self.user_id,
        )

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.success is False

    def test_execute_calls_repository_once(self):
        """Execute calls repository exactly once."""
        # Arrange
        notification_id = 42
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=True, recipient_id=str(self.user_id))
        command = MarkNotificationReadCommand(
            notification_id=notification_id,
            user_id=self.user_id,
        )

        # Act
        self.use_case.execute(command)

        # Assert
        self.mock_repo.mark_read.assert_called_once()

    def test_execute_passes_correct_notification_id(self):
        """Execute passes the correct notification_id to repository."""
        # Arrange
        notification_id = 123
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=True, recipient_id=str(self.user_id))
        command = MarkNotificationReadCommand(
            notification_id=notification_id,
            user_id=self.user_id,
        )

        # Act
        self.use_case.execute(command)

        # Assert
        self.mock_repo.mark_read.assert_called_once_with(notification_id)

    def test_execute_returns_notification_id_in_result(self):
        """Execute returns the notification_id in result."""
        # Arrange
        notification_id = 999
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=True, recipient_id=str(self.user_id))
        command = MarkNotificationReadCommand(
            notification_id=notification_id,
            user_id=self.user_id,
        )

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.notification_id == notification_id

    def test_execute_with_multiple_commands(self):
        """Execute handles multiple sequential commands."""
        # Arrange
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=True, recipient_id=str(self.user_id))

        # Act & Assert
        for notif_id in [1, 2, 3]:
            command = MarkNotificationReadCommand(
                notification_id=notif_id,
                user_id=self.user_id,
            )
            result = self.use_case.execute(command)

            assert result.success is True
            assert result.notification_id == notif_id

        assert self.mock_repo.mark_read.call_count == 3

    def test_execute_repository_exception_propagates(self):
        """Execute propagates repository exceptions."""
        # Arrange
        self.mock_repo.mark_read.side_effect = Exception("Database error")
        command = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        # Act & Assert
        with self.assertRaises(Exception):
            self.use_case.execute(command)


class TestMarkAllNotificationsReadUseCase(unittest.TestCase):
    """Tests for MarkAllNotificationsReadUseCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_repo = Mock()
        self.use_case = MarkAllNotificationsReadUseCase(notification_repo=self.mock_repo)
        self.user_id = uuid4()
        self.workspace_id = uuid4()

    def test_use_case_initialization(self):
        """Verify use case initializes with repository."""
        assert self.use_case._repo == self.mock_repo

    def test_execute_marks_all_as_read_global(self):
        """Execute marks all notifications as read for a user (global)."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 10
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.updated_count == 10
        self.mock_repo.mark_all_read.assert_called_once_with(
            self.user_id,
            workspace_id=None,
        )

    def test_execute_marks_all_as_read_workspace_scoped(self):
        """Execute marks all notifications as read for a user in a workspace."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 5
        command = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.updated_count == 5
        self.mock_repo.mark_all_read.assert_called_once_with(
            self.user_id,
            workspace_id=self.workspace_id,
        )

    def test_execute_returns_zero_when_no_unread(self):
        """Execute returns 0 when no unread notifications."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 0
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.updated_count == 0

    def test_execute_passes_user_id_to_repository(self):
        """Execute passes the correct user_id to repository."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 0
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        # Act
        self.use_case.execute(command)

        # Assert
        call_args = self.mock_repo.mark_all_read.call_args
        assert call_args[0][0] == self.user_id

    def test_execute_passes_workspace_id_to_repository(self):
        """Execute passes the correct workspace_id to repository."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 0
        command = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        # Act
        self.use_case.execute(command)

        # Assert
        call_kwargs = self.mock_repo.mark_all_read.call_args[1]
        assert call_kwargs["workspace_id"] == self.workspace_id

    def test_execute_with_none_workspace_id(self):
        """Execute handles None workspace_id correctly."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 10
        command = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=None,
        )

        # Act
        self.use_case.execute(command)

        # Assert
        self.mock_repo.mark_all_read.assert_called_once_with(
            self.user_id,
            workspace_id=None,
        )

    def test_execute_large_update_count(self):
        """Execute handles large update counts."""
        # Arrange
        large_count = 10000
        self.mock_repo.mark_all_read.return_value = large_count
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        # Act
        result = self.use_case.execute(command)

        # Assert
        assert result.updated_count == large_count

    def test_execute_repository_called_once(self):
        """Execute calls repository exactly once."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 5
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        # Act
        self.use_case.execute(command)

        # Assert
        self.mock_repo.mark_all_read.assert_called_once()

    def test_execute_different_workspaces(self):
        """Execute handles different workspaces correctly."""
        # Arrange
        workspace1_id = uuid4()
        workspace2_id = uuid4()
        self.mock_repo.mark_all_read.side_effect = [5, 3]

        # Act
        result1 = self.use_case.execute(
            MarkAllNotificationsReadCommand(
                user_id=self.user_id,
                workspace_id=workspace1_id,
            )
        )
        result2 = self.use_case.execute(
            MarkAllNotificationsReadCommand(
                user_id=self.user_id,
                workspace_id=workspace2_id,
            )
        )

        # Assert
        assert result1.updated_count == 5
        assert result2.updated_count == 3
        assert self.mock_repo.mark_all_read.call_count == 2

    def test_execute_repository_exception_propagates(self):
        """Execute propagates repository exceptions."""
        # Arrange
        self.mock_repo.mark_all_read.side_effect = Exception("Database error")
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        # Act & Assert
        with self.assertRaises(Exception):
            self.use_case.execute(command)


class TestUseCaseIntegration(unittest.TestCase):
    """Integration tests for use cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_repo = Mock()
        self.single_read_use_case = MarkNotificationReadUseCase(
            notification_repo=self.mock_repo
        )
        self.batch_read_use_case = MarkAllNotificationsReadUseCase(
            notification_repo=self.mock_repo
        )
        self.user_id = uuid4()
        self.workspace_id = uuid4()

    def test_single_then_batch_operations(self):
        """Test executing single and batch operations in sequence."""
        # Arrange
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=True, recipient_id=str(self.user_id))
        self.mock_repo.mark_all_read.return_value = 5

        # Act
        single_result = self.single_read_use_case.execute(
            MarkNotificationReadCommand(
                notification_id=1,
                user_id=self.user_id,
            )
        )

        batch_result = self.batch_read_use_case.execute(
            MarkAllNotificationsReadCommand(user_id=self.user_id)
        )

        # Assert
        assert single_result.success is True
        assert batch_result.updated_count == 5

    def test_multiple_single_reads_then_batch(self):
        """Test multiple single reads followed by batch operation."""
        # Arrange
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=True, recipient_id=str(self.user_id))
        self.mock_repo.mark_all_read.return_value = 10

        # Act - mark individual notifications
        for notif_id in [1, 2, 3]:
            result = self.single_read_use_case.execute(
                MarkNotificationReadCommand(
                    notification_id=notif_id,
                    user_id=self.user_id,
                )
            )
            assert result.success is True

        # Act - mark all remaining
        batch_result = self.batch_read_use_case.execute(
            MarkAllNotificationsReadCommand(user_id=self.user_id)
        )

        # Assert
        assert batch_result.updated_count == 10

    def test_workspace_scoped_operations(self):
        """Test that workspace_id is properly passed through use cases."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 7

        # Act
        result = self.batch_read_use_case.execute(
            MarkAllNotificationsReadCommand(
                user_id=self.user_id,
                workspace_id=self.workspace_id,
            )
        )

        # Assert
        assert result.updated_count == 7
        call_kwargs = self.mock_repo.mark_all_read.call_args[1]
        assert call_kwargs["workspace_id"] == self.workspace_id


class TestUseCaseErrorHandling(unittest.TestCase):
    """Tests for error handling in use cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_repo = Mock()
        self.single_use_case = MarkNotificationReadUseCase(
            notification_repo=self.mock_repo
        )
        self.batch_use_case = MarkAllNotificationsReadUseCase(
            notification_repo=self.mock_repo
        )
        self.user_id = uuid4()

    def test_single_read_repository_failure(self):
        """Single read use case handles repository failure."""
        # Arrange
        self.mock_repo.mark_read.side_effect = RuntimeError("Connection lost")

        # Act & Assert
        with self.assertRaises(RuntimeError):
            self.single_use_case.execute(
                MarkNotificationReadCommand(notification_id=1, user_id=self.user_id)
            )

    def test_batch_read_repository_failure(self):
        """Batch read use case handles repository failure."""
        # Arrange
        self.mock_repo.mark_all_read.side_effect = RuntimeError("Connection lost")

        # Act & Assert
        with self.assertRaises(RuntimeError):
            self.batch_use_case.execute(
                MarkAllNotificationsReadCommand(user_id=self.user_id)
            )

    def test_single_read_returns_false_on_not_found(self):
        """Single read returns failure when notification not found."""
        # Arrange
        self.mock_repo.mark_read.return_value = MarkReadOutcome(changed=False)

        # Act
        result = self.single_use_case.execute(
            MarkNotificationReadCommand(notification_id=999, user_id=self.user_id)
        )

        # Assert
        assert result.success is False

    def test_batch_read_returns_zero_when_no_updates(self):
        """Batch read returns 0 when no notifications updated."""
        # Arrange
        self.mock_repo.mark_all_read.return_value = 0

        # Act
        result = self.batch_use_case.execute(
            MarkAllNotificationsReadCommand(user_id=self.user_id)
        )

        # Assert
        assert result.updated_count == 0


if __name__ == "__main__":
    unittest.main()
