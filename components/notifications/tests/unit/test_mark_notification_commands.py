"""Unit tests for mark notification command value objects."""

from __future__ import annotations

from uuid import uuid4

import unittest

from components.notifications.application.commands.mark_notifications_command import (
    MarkAllNotificationsReadCommand,
    MarkAllNotificationsReadResult,
    MarkNotificationReadCommand,
    MarkNotificationReadResult,
)


class TestMarkNotificationReadCommand(unittest.TestCase):
    """Tests for MarkNotificationReadCommand value object."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()

    def test_command_creation(self):
        """Create a mark notification read command."""
        command = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        assert command.notification_id == 1
        assert command.user_id == self.user_id

    def test_command_with_large_notification_id(self):
        """Test command with large notification ID."""
        large_id = 9999999
        command = MarkNotificationReadCommand(
            notification_id=large_id,
            user_id=self.user_id,
        )

        assert command.notification_id == large_id

    def test_command_is_frozen(self):
        """Verify that command is immutable."""
        command = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        with self.assertRaises(Exception):  # FrozenInstanceError
            command.notification_id = 2

    def test_command_equality(self):
        """Two commands with same data are equal."""
        command1 = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        command2 = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        assert command1 == command2

    def test_command_inequality(self):
        """Two commands with different data are not equal."""
        command1 = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        command2 = MarkNotificationReadCommand(
            notification_id=2,
            user_id=self.user_id,
        )

        assert command1 != command2

    def test_command_different_user_ids(self):
        """Commands with different user IDs are not equal."""
        user_id1 = uuid4()
        user_id2 = uuid4()

        command1 = MarkNotificationReadCommand(
            notification_id=1,
            user_id=user_id1,
        )

        command2 = MarkNotificationReadCommand(
            notification_id=1,
            user_id=user_id2,
        )

        assert command1 != command2


class TestMarkNotificationReadResult(unittest.TestCase):
    """Tests for MarkNotificationReadResult value object."""

    def test_result_successful(self):
        """Create a successful result."""
        result = MarkNotificationReadResult(
            success=True,
            notification_id=1,
        )

        assert result.success is True
        assert result.notification_id == 1

    def test_result_unsuccessful(self):
        """Create an unsuccessful result."""
        result = MarkNotificationReadResult(
            success=False,
            notification_id=1,
        )

        assert result.success is False
        assert result.notification_id == 1

    def test_result_not_found(self):
        """Result when notification was not found."""
        result = MarkNotificationReadResult(
            success=False,
            notification_id=999,
        )

        assert result.success is False

    def test_result_is_frozen(self):
        """Verify that result is immutable."""
        result = MarkNotificationReadResult(
            success=True,
            notification_id=1,
        )

        with self.assertRaises(Exception):  # FrozenInstanceError
            result.success = False

    def test_result_equality(self):
        """Two results with same data are equal."""
        result1 = MarkNotificationReadResult(
            success=True,
            notification_id=1,
        )

        result2 = MarkNotificationReadResult(
            success=True,
            notification_id=1,
        )

        assert result1 == result2

    def test_result_inequality(self):
        """Two results with different data are not equal."""
        result1 = MarkNotificationReadResult(
            success=True,
            notification_id=1,
        )

        result2 = MarkNotificationReadResult(
            success=False,
            notification_id=1,
        )

        assert result1 != result2


class TestMarkAllNotificationsReadCommand(unittest.TestCase):
    """Tests for MarkAllNotificationsReadCommand value object."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()

    def test_command_user_id_only(self):
        """Create command with only user_id."""
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        assert command.user_id == self.user_id
        assert command.workspace_id is None

    def test_command_with_workspace_id(self):
        """Create command with user_id and workspace_id."""
        command = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        assert command.user_id == self.user_id
        assert command.workspace_id == self.workspace_id

    def test_command_workspace_id_optional(self):
        """workspace_id is optional in the command."""
        command = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=None,
        )

        assert command.workspace_id is None

    def test_command_is_frozen(self):
        """Verify that command is immutable."""
        command = MarkAllNotificationsReadCommand(user_id=self.user_id)

        with self.assertRaises(Exception):  # FrozenInstanceError
            command.user_id = uuid4()

    def test_command_equality_without_workspace(self):
        """Two commands without workspace are equal if user_id matches."""
        command1 = MarkAllNotificationsReadCommand(user_id=self.user_id)
        command2 = MarkAllNotificationsReadCommand(user_id=self.user_id)

        assert command1 == command2

    def test_command_equality_with_workspace(self):
        """Two commands with same user and workspace are equal."""
        command1 = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        command2 = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        assert command1 == command2

    def test_command_inequality_different_workspace(self):
        """Commands with different workspaces are not equal."""
        workspace1_id = uuid4()
        workspace2_id = uuid4()

        command1 = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=workspace1_id,
        )

        command2 = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=workspace2_id,
        )

        assert command1 != command2

    def test_command_with_and_without_workspace_not_equal(self):
        """Command with and without workspace_id are not equal."""
        command_global = MarkAllNotificationsReadCommand(user_id=self.user_id)

        command_scoped = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        assert command_global != command_scoped


class TestMarkAllNotificationsReadResult(unittest.TestCase):
    """Tests for MarkAllNotificationsReadResult value object."""

    def test_result_zero_updated(self):
        """Create result with zero notifications updated."""
        result = MarkAllNotificationsReadResult(updated_count=0)

        assert result.updated_count == 0

    def test_result_single_updated(self):
        """Create result with single notification updated."""
        result = MarkAllNotificationsReadResult(updated_count=1)

        assert result.updated_count == 1

    def test_result_multiple_updated(self):
        """Create result with multiple notifications updated."""
        result = MarkAllNotificationsReadResult(updated_count=42)

        assert result.updated_count == 42

    def test_result_large_count(self):
        """Create result with large notification count."""
        large_count = 100000
        result = MarkAllNotificationsReadResult(updated_count=large_count)

        assert result.updated_count == large_count

    def test_result_is_frozen(self):
        """Verify that result is immutable."""
        result = MarkAllNotificationsReadResult(updated_count=5)

        with self.assertRaises(Exception):  # FrozenInstanceError
            result.updated_count = 10

    def test_result_equality(self):
        """Two results with same count are equal."""
        result1 = MarkAllNotificationsReadResult(updated_count=5)
        result2 = MarkAllNotificationsReadResult(updated_count=5)

        assert result1 == result2

    def test_result_inequality(self):
        """Two results with different counts are not equal."""
        result1 = MarkAllNotificationsReadResult(updated_count=5)
        result2 = MarkAllNotificationsReadResult(updated_count=10)

        assert result1 != result2


class TestCommandAndResultIntegration(unittest.TestCase):
    """Tests for command and result usage patterns."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()

    def test_single_mark_command_result_flow(self):
        """Test flow of single mark notification command."""
        command = MarkNotificationReadCommand(
            notification_id=42,
            user_id=self.user_id,
        )

        result = MarkNotificationReadResult(
            success=True,
            notification_id=command.notification_id,
        )

        assert result.notification_id == command.notification_id
        assert result.success is True

    def test_batch_mark_command_result_flow(self):
        """Test flow of batch mark all notifications command."""
        command = MarkAllNotificationsReadCommand(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        result = MarkAllNotificationsReadResult(updated_count=15)

        assert result.updated_count == 15

    def test_commands_are_hashable(self):
        """Commands can be used in sets/dicts."""
        command1 = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        command2 = MarkNotificationReadCommand(
            notification_id=1,
            user_id=self.user_id,
        )

        commands_set = {command1, command2}
        assert len(commands_set) == 1  # Duplicates removed

    def test_results_are_hashable(self):
        """Results can be used in sets/dicts."""
        result1 = MarkNotificationReadResult(success=True, notification_id=1)
        result2 = MarkNotificationReadResult(success=True, notification_id=1)

        results_set = {result1, result2}
        assert len(results_set) == 1  # Duplicates removed


if __name__ == "__main__":
    unittest.main()
