"""Unit tests for NotificationFilter value object."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import unittest

from components.notifications.domain.value_objects.notification_filter import (
    NotificationFilter,
)


class TestNotificationFilterConstruction(unittest.TestCase):
    """Tests for NotificationFilter instantiation."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_notification_filter_with_user_id_only(self):
        """Create filter with only required user_id."""
        filter_obj = NotificationFilter(user_id=self.user_id)

        assert filter_obj.user_id == self.user_id
        assert filter_obj.is_read is None
        assert filter_obj.notification_type is None
        assert filter_obj.workspace_id is None
        assert filter_obj.created_after is None
        assert filter_obj.created_before is None
        assert filter_obj.period is None

    def test_notification_filter_with_all_fields(self):
        """Create filter with all fields populated."""
        created_after = self.now - timedelta(days=7)
        created_before = self.now

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            is_read=False,
            notification_type="like",
            workspace_id=self.workspace_id,
            created_after=created_after,
            created_before=created_before,
            period="last_7_days",
        )

        assert filter_obj.user_id == self.user_id
        assert filter_obj.is_read is False
        assert filter_obj.notification_type == "like"
        assert filter_obj.workspace_id == self.workspace_id
        assert filter_obj.created_after == created_after
        assert filter_obj.created_before == created_before
        assert filter_obj.period == "last_7_days"

    def test_notification_filter_is_frozen(self):
        """Verify that NotificationFilter is immutable."""
        filter_obj = NotificationFilter(user_id=self.user_id)

        with self.assertRaises(Exception):  # FrozenInstanceError
            filter_obj.is_read = True

    def test_notification_filter_equality(self):
        """Two filters with same data are equal."""
        filter1 = NotificationFilter(
            user_id=self.user_id,
            is_read=True,
            notification_type="comment",
        )

        filter2 = NotificationFilter(
            user_id=self.user_id,
            is_read=True,
            notification_type="comment",
        )

        assert filter1 == filter2

    def test_notification_filter_inequality(self):
        """Two filters with different data are not equal."""
        filter1 = NotificationFilter(user_id=self.user_id, is_read=True)
        filter2 = NotificationFilter(user_id=self.user_id, is_read=False)

        assert filter1 != filter2


class TestNotificationFilterReadState(unittest.TestCase):
    """Tests for is_read filter state."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()

    def test_filter_unread_notifications(self):
        """Create filter for unread notifications only."""
        filter_obj = NotificationFilter(user_id=self.user_id, is_read=False)

        assert filter_obj.is_read is False

    def test_filter_read_notifications(self):
        """Create filter for read notifications only."""
        filter_obj = NotificationFilter(user_id=self.user_id, is_read=True)

        assert filter_obj.is_read is True

    def test_filter_all_notifications_regardless_of_read_state(self):
        """Create filter that matches all notifications regardless of read state."""
        filter_obj = NotificationFilter(user_id=self.user_id, is_read=None)

        assert filter_obj.is_read is None


class TestNotificationFilterByType(unittest.TestCase):
    """Tests for filtering by notification type."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()

    def test_filter_by_like_type(self):
        """Filter for like notifications."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            notification_type="like",
        )

        assert filter_obj.notification_type == "like"

    def test_filter_by_comment_type(self):
        """Filter for comment notifications."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            notification_type="comment",
        )

        assert filter_obj.notification_type == "comment"

    def test_filter_by_system_type(self):
        """Filter for system notifications."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            notification_type="system",
        )

        assert filter_obj.notification_type == "system"

    def test_filter_by_ai_event_type(self):
        """Filter for AI event notifications."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            notification_type="ai_event",
        )

        assert filter_obj.notification_type == "ai_event"

    def test_filter_all_types(self):
        """Create filter with no type restriction."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            notification_type=None,
        )

        assert filter_obj.notification_type is None

    def test_filter_by_multiple_type_patterns(self):
        """Test filters for different notification types."""
        types = ["like", "comment", "follow", "mention", "message", "system"]

        for notification_type in types:
            filter_obj = NotificationFilter(
                user_id=self.user_id,
                notification_type=notification_type,
            )

            assert filter_obj.notification_type == notification_type


class TestNotificationFilterByWorkspace(unittest.TestCase):
    """Tests for filtering by workspace."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()

    def test_filter_by_workspace_id(self):
        """Filter notifications for a specific workspace."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
        )

        assert filter_obj.workspace_id == self.workspace_id

    def test_filter_workspace_agnostic_notifications(self):
        """Filter notifications without workspace scope."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            workspace_id=None,
        )

        assert filter_obj.workspace_id is None

    def test_filter_different_workspaces(self):
        """Filters for different workspaces are distinct."""
        workspace1_id = uuid4()
        workspace2_id = uuid4()

        filter1 = NotificationFilter(
            user_id=self.user_id,
            workspace_id=workspace1_id,
        )

        filter2 = NotificationFilter(
            user_id=self.user_id,
            workspace_id=workspace2_id,
        )

        assert filter1 != filter2


class TestNotificationFilterByDateRange(unittest.TestCase):
    """Tests for date range filtering."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_filter_created_after_date(self):
        """Filter notifications created after a specific date."""
        created_after = self.now - timedelta(days=7)

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            created_after=created_after,
        )

        assert filter_obj.created_after == created_after
        assert filter_obj.created_before is None

    def test_filter_created_before_date(self):
        """Filter notifications created before a specific date."""
        created_before = self.now - timedelta(days=1)

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            created_before=created_before,
        )

        assert filter_obj.created_before == created_before
        assert filter_obj.created_after is None

    def test_filter_date_range(self):
        """Filter notifications within a specific date range."""
        created_after = self.now - timedelta(days=30)
        created_before = self.now

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            created_after=created_after,
            created_before=created_before,
        )

        assert filter_obj.created_after == created_after
        assert filter_obj.created_before == created_before

    def test_filter_before_after_ordering(self):
        """Verify after date is before the before date."""
        created_after = self.now - timedelta(days=30)
        created_before = self.now

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            created_after=created_after,
            created_before=created_before,
        )

        assert filter_obj.created_after < filter_obj.created_before

    def test_filter_same_day_range(self):
        """Filter for notifications from a single day."""
        start_of_day = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            created_after=start_of_day,
            created_before=end_of_day,
        )

        assert filter_obj.created_after == start_of_day
        assert filter_obj.created_before == end_of_day


class TestNotificationFilterByPeriod(unittest.TestCase):
    """Tests for period-based filtering."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()

    def test_filter_period_today(self):
        """Filter for notifications from today."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            period="today",
        )

        assert filter_obj.period == "today"

    def test_filter_period_last_7_days(self):
        """Filter for notifications from last 7 days."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            period="last_7_days",
        )

        assert filter_obj.period == "last_7_days"

    def test_filter_period_last_30_days(self):
        """Filter for notifications from last 30 days."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            period="last_30_days",
        )

        assert filter_obj.period == "last_30_days"

    def test_filter_no_period_restriction(self):
        """Filter with no period restriction."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            period=None,
        )

        assert filter_obj.period is None

    def test_filter_all_supported_periods(self):
        """Test all supported period values."""
        periods = ["today", "last_7_days", "last_30_days"]

        for period in periods:
            filter_obj = NotificationFilter(
                user_id=self.user_id,
                period=period,
            )

            assert filter_obj.period == period


class TestNotificationFilterComplexScenarios(unittest.TestCase):
    """Tests for complex filtering scenarios."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_filter_unread_likes_in_workspace(self):
        """Filter for unread like notifications in a specific workspace."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            is_read=False,
            notification_type="like",
            workspace_id=self.workspace_id,
        )

        assert filter_obj.is_read is False
        assert filter_obj.notification_type == "like"
        assert filter_obj.workspace_id == self.workspace_id

    def test_filter_recent_unread_in_workspace(self):
        """Filter for recent unread notifications in a workspace."""
        created_after = self.now - timedelta(days=7)

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            is_read=False,
            workspace_id=self.workspace_id,
            created_after=created_after,
            period="last_7_days",
        )

        assert filter_obj.is_read is False
        assert filter_obj.workspace_id == self.workspace_id
        assert filter_obj.period == "last_7_days"

    def test_filter_all_today_comments(self):
        """Filter for all comment notifications from today."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            notification_type="comment",
            period="today",
        )

        assert filter_obj.notification_type == "comment"
        assert filter_obj.period == "today"

    def test_filter_read_messages_before_date(self):
        """Filter for read messages before a specific date."""
        created_before = self.now - timedelta(days=30)

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            is_read=True,
            notification_type="message",
            created_before=created_before,
        )

        assert filter_obj.is_read is True
        assert filter_obj.notification_type == "message"
        assert filter_obj.created_before == created_before

    def test_filter_system_notifications_regardless_workspace(self):
        """Filter for system notifications (workspace-agnostic)."""
        filter_obj = NotificationFilter(
            user_id=self.user_id,
            notification_type="system",
            workspace_id=None,
        )

        assert filter_obj.notification_type == "system"
        assert filter_obj.workspace_id is None


class TestNotificationFilterDataIntegrity(unittest.TestCase):
    """Tests for data integrity and consistency."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_filter_preserves_all_fields(self):
        """Verify all filter fields are preserved through access."""
        created_after = self.now - timedelta(days=30)
        created_before = self.now

        filter_obj = NotificationFilter(
            user_id=self.user_id,
            is_read=False,
            notification_type="mention",
            workspace_id=self.workspace_id,
            created_after=created_after,
            created_before=created_before,
            period="last_30_days",
        )

        # Access all fields
        assert filter_obj.user_id == self.user_id
        assert filter_obj.is_read is False
        assert filter_obj.notification_type == "mention"
        assert filter_obj.workspace_id == self.workspace_id
        assert filter_obj.created_after == created_after
        assert filter_obj.created_before == created_before
        assert filter_obj.period == "last_30_days"

    def test_filter_with_partial_date_range(self):
        """Filter can have only start or end date, not both."""
        created_after = self.now - timedelta(days=7)

        filter_with_start = NotificationFilter(
            user_id=self.user_id,
            created_after=created_after,
        )

        created_before = self.now

        filter_with_end = NotificationFilter(
            user_id=self.user_id,
            created_before=created_before,
        )

        assert filter_with_start.created_after is not None
        assert filter_with_start.created_before is None
        assert filter_with_end.created_after is None
        assert filter_with_end.created_before is not None


if __name__ == "__main__":
    unittest.main()
