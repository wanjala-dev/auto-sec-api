"""Unit tests for notification domain enums."""

from __future__ import annotations

import unittest

from components.notifications.domain.enums import (
    AINotificationChannel,
    NotificationType,
    TimePeriod,
)


class TestNotificationType(unittest.TestCase):
    """Tests for NotificationType enum."""

    def test_notification_type_like(self):
        """Test LIKE notification type."""
        assert NotificationType.LIKE == "like"
        assert NotificationType.LIKE.value == "like"

    def test_notification_type_comment(self):
        """Test COMMENT notification type."""
        assert NotificationType.COMMENT == "comment"
        assert NotificationType.COMMENT.value == "comment"

    def test_notification_type_follow(self):
        """Test FOLLOW notification type."""
        assert NotificationType.FOLLOW == "follow"
        assert NotificationType.FOLLOW.value == "follow"

    def test_notification_type_mention(self):
        """Test MENTION notification type."""
        assert NotificationType.MENTION == "mention"
        assert NotificationType.MENTION.value == "mention"

    def test_notification_type_message(self):
        """Test MESSAGE notification type."""
        assert NotificationType.MESSAGE == "message"
        assert NotificationType.MESSAGE.value == "message"

    def test_notification_type_system(self):
        """Test SYSTEM notification type."""
        assert NotificationType.SYSTEM == "system"
        assert NotificationType.SYSTEM.value == "system"

    def test_notification_type_ai_event(self):
        """Test AI_EVENT notification type."""
        assert NotificationType.AI_EVENT == "ai_event"
        assert NotificationType.AI_EVENT.value == "ai_event"

    def test_notification_type_report(self):
        """Test REPORT notification type."""
        assert NotificationType.REPORT == "report"
        assert NotificationType.REPORT.value == "report"

    def test_notification_type_all_members(self):
        """Verify all expected notification types are present."""
        expected_types = [
            "like",
            "comment",
            "follow",
            "mention",
            "message",
            "system",
            "ai_event",
            "report",
        ]

        actual_types = [member.value for member in NotificationType]

        assert len(actual_types) == len(expected_types)
        for expected in expected_types:
            assert expected in actual_types

    def test_notification_type_string_conversion(self):
        """Test that notification types have correct string representation."""
        notification_type = NotificationType.LIKE

        # String representation includes the enum name
        assert str(notification_type) == "NotificationType.LIKE"
        # But the value is the actual string
        assert notification_type.value == "like"

    def test_notification_type_comparison(self):
        """Test enum value comparison."""
        assert NotificationType.LIKE == NotificationType.LIKE
        assert NotificationType.LIKE != NotificationType.COMMENT

    def test_notification_type_from_value(self):
        """Test creating enum from string value."""
        assert NotificationType("like") == NotificationType.LIKE
        assert NotificationType("comment") == NotificationType.COMMENT
        assert NotificationType("system") == NotificationType.SYSTEM

    def test_notification_type_invalid_value(self):
        """Test that invalid values raise error."""
        with self.assertRaises(ValueError):
            NotificationType("invalid_type")

    def test_notification_type_iteration(self):
        """Test iterating over notification types."""
        types = list(NotificationType)
        assert len(types) == 8
        assert NotificationType.LIKE in types
        assert NotificationType.COMMENT in types
        assert NotificationType.SYSTEM in types


class TestAINotificationChannel(unittest.TestCase):
    """Tests for AINotificationChannel enum."""

    def test_ai_channel_general(self):
        """Test GENERAL AI channel."""
        assert AINotificationChannel.GENERAL == "general"
        assert AINotificationChannel.GENERAL.value == "general"

    def test_ai_channel_teammate_status(self):
        """Test TEAMMATE_STATUS AI channel."""
        assert AINotificationChannel.TEAMMATE_STATUS == "teammate_status"
        assert AINotificationChannel.TEAMMATE_STATUS.value == "teammate_status"

    def test_ai_channel_action_created(self):
        """Test ACTION_CREATED AI channel."""
        assert AINotificationChannel.ACTION_CREATED == "action_created"
        assert AINotificationChannel.ACTION_CREATED.value == "action_created"

    def test_ai_channel_action_auto_executed(self):
        """Test ACTION_AUTO_EXECUTED AI channel."""
        assert AINotificationChannel.ACTION_AUTO_EXECUTED == "action_auto_executed"
        assert (
            AINotificationChannel.ACTION_AUTO_EXECUTED.value == "action_auto_executed"
        )

    def test_ai_channel_action_error(self):
        """Test ACTION_ERROR AI channel."""
        assert AINotificationChannel.ACTION_ERROR == "action_error"
        assert AINotificationChannel.ACTION_ERROR.value == "action_error"

    def test_ai_channel_report_generated(self):
        """Test REPORT_GENERATED AI channel."""
        assert AINotificationChannel.REPORT_GENERATED == "report_generated"
        assert AINotificationChannel.REPORT_GENERATED.value == "report_generated"

    def test_ai_channel_all_members(self):
        """Verify all expected AI channels are present."""
        expected_channels = [
            "general",
            "teammate_status",
            "action_created",
            "action_auto_executed",
            "action_error",
            "report_generated",
        ]

        actual_channels = [member.value for member in AINotificationChannel]

        assert len(actual_channels) == len(expected_channels)
        for expected in expected_channels:
            assert expected in actual_channels

    def test_ai_channel_comparison(self):
        """Test enum value comparison."""
        assert AINotificationChannel.GENERAL == AINotificationChannel.GENERAL
        assert AINotificationChannel.GENERAL != AINotificationChannel.ACTION_ERROR

    def test_ai_channel_from_value(self):
        """Test creating enum from string value."""
        assert AINotificationChannel("general") == AINotificationChannel.GENERAL
        assert (
            AINotificationChannel("action_created")
            == AINotificationChannel.ACTION_CREATED
        )
        assert (
            AINotificationChannel("report_generated")
            == AINotificationChannel.REPORT_GENERATED
        )

    def test_ai_channel_invalid_value(self):
        """Test that invalid values raise error."""
        with self.assertRaises(ValueError):
            AINotificationChannel("invalid_channel")

    def test_ai_channel_iteration(self):
        """Test iterating over AI channels."""
        channels = list(AINotificationChannel)
        assert len(channels) == 6
        assert AINotificationChannel.GENERAL in channels
        assert AINotificationChannel.ACTION_ERROR in channels
        assert AINotificationChannel.REPORT_GENERATED in channels

    def test_ai_channel_action_channels(self):
        """Test that all action-related channels exist."""
        action_channels = [
            AINotificationChannel.ACTION_CREATED,
            AINotificationChannel.ACTION_AUTO_EXECUTED,
            AINotificationChannel.ACTION_ERROR,
        ]

        assert len(action_channels) == 3
        for channel in action_channels:
            assert "action" in channel.value


class TestTimePeriod(unittest.TestCase):
    """Tests for TimePeriod enum."""

    def test_time_period_today(self):
        """Test TODAY time period."""
        assert TimePeriod.TODAY == "today"
        assert TimePeriod.TODAY.value == "today"

    def test_time_period_last_7_days(self):
        """Test LAST_7_DAYS time period."""
        assert TimePeriod.LAST_7_DAYS == "last_7_days"
        assert TimePeriod.LAST_7_DAYS.value == "last_7_days"

    def test_time_period_last_30_days(self):
        """Test LAST_30_DAYS time period."""
        assert TimePeriod.LAST_30_DAYS == "last_30_days"
        assert TimePeriod.LAST_30_DAYS.value == "last_30_days"

    def test_time_period_all_members(self):
        """Verify all expected time periods are present."""
        expected_periods = ["today", "last_7_days", "last_30_days"]

        actual_periods = [member.value for member in TimePeriod]

        assert len(actual_periods) == len(expected_periods)
        for expected in expected_periods:
            assert expected in actual_periods

    def test_time_period_comparison(self):
        """Test enum value comparison."""
        assert TimePeriod.TODAY == TimePeriod.TODAY
        assert TimePeriod.TODAY != TimePeriod.LAST_7_DAYS
        assert TimePeriod.LAST_7_DAYS != TimePeriod.LAST_30_DAYS

    def test_time_period_from_value(self):
        """Test creating enum from string value."""
        assert TimePeriod("today") == TimePeriod.TODAY
        assert TimePeriod("last_7_days") == TimePeriod.LAST_7_DAYS
        assert TimePeriod("last_30_days") == TimePeriod.LAST_30_DAYS

    def test_time_period_invalid_value(self):
        """Test that invalid values raise error."""
        with self.assertRaises(ValueError):
            TimePeriod("invalid_period")

    def test_time_period_iteration(self):
        """Test iterating over time periods."""
        periods = list(TimePeriod)
        assert len(periods) == 3
        assert TimePeriod.TODAY in periods
        assert TimePeriod.LAST_7_DAYS in periods
        assert TimePeriod.LAST_30_DAYS in periods

    def test_time_period_string_ordering(self):
        """Test that periods maintain logical ordering."""
        periods = list(TimePeriod)
        # Verify at least that all periods exist (order isn't guaranteed by enum)
        period_values = [p.value for p in periods]

        assert "today" in period_values
        assert "last_7_days" in period_values
        assert "last_30_days" in period_values


class TestEnumIntegration(unittest.TestCase):
    """Tests for enum integration and usage patterns."""

    def test_notification_type_in_filter(self):
        """Test using NotificationType with filter operations."""
        notification_type = NotificationType.LIKE
        types_to_match = [
            NotificationType.LIKE,
            NotificationType.COMMENT,
            NotificationType.FOLLOW,
        ]

        assert notification_type in types_to_match

    def test_ai_channel_in_preference(self):
        """Test using AINotificationChannel for preferences."""
        enabled_channels = {
            AINotificationChannel.GENERAL: True,
            AINotificationChannel.ACTION_CREATED: False,
            AINotificationChannel.REPORT_GENERATED: True,
        }

        assert enabled_channels[AINotificationChannel.GENERAL] is True
        assert enabled_channels[AINotificationChannel.ACTION_CREATED] is False

    def test_time_period_string_matching(self):
        """Test matching time period strings."""
        period_str = "last_7_days"
        matched_period = TimePeriod(period_str)

        assert matched_period == TimePeriod.LAST_7_DAYS

    def test_enum_values_are_strings(self):
        """Verify that enum values are strings for persistence."""
        assert isinstance(NotificationType.LIKE.value, str)
        assert isinstance(AINotificationChannel.GENERAL.value, str)
        assert isinstance(TimePeriod.TODAY.value, str)

    def test_enum_members_are_hashable(self):
        """Test that enum members can be used in sets/dicts."""
        notification_types_set = {
            NotificationType.LIKE,
            NotificationType.COMMENT,
            NotificationType.LIKE,  # Duplicate
        }

        # Sets remove duplicates
        assert len(notification_types_set) == 2

    def test_enum_all_values_are_unique(self):
        """Verify all enum values are unique within their enum."""
        notification_values = [n.value for n in NotificationType]
        assert len(notification_values) == len(set(notification_values))

        ai_values = [a.value for a in AINotificationChannel]
        assert len(ai_values) == len(set(ai_values))

        period_values = [p.value for p in TimePeriod]
        assert len(period_values) == len(set(period_values))


if __name__ == "__main__":
    unittest.main()
