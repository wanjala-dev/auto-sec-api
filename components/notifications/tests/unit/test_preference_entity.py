"""Unit tests for notification preference domain entities."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import unittest

from components.notifications.domain.entities.preference_entity import (
    AINotificationPreferenceEntity,
    UserPreferenceEntity,
    WorkspaceNotificationPreferenceEntity,
)


class TestUserPreferenceEntityConstruction(unittest.TestCase):
    """Tests for UserPreferenceEntity instantiation."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()

    def test_user_preference_entity_all_fields(self):
        """Create a UserPreferenceEntity with all fields."""
        preference = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="dark",
            language="en",
            email_notifications=True,
            push_notifications=True,
            notifications_enabled=True,
        )

        assert preference.id == 1
        assert preference.user_id == self.user_id
        assert preference.darkmode == "dark"
        assert preference.language == "en"
        assert preference.email_notifications is True
        assert preference.push_notifications is True
        assert preference.notifications_enabled is True

    def test_user_preference_entity_with_darkmode_disabled(self):
        """Create preference with dark mode disabled."""
        preference = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="light",
            language="en",
            email_notifications=True,
            push_notifications=False,
            notifications_enabled=True,
        )

        assert preference.darkmode == "light"
        assert preference.push_notifications is False

    def test_user_preference_entity_with_notifications_disabled(self):
        """Create preference with all notifications disabled."""
        preference = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="dark",
            language="en",
            email_notifications=False,
            push_notifications=False,
            notifications_enabled=False,
        )

        assert preference.notifications_enabled is False
        assert preference.email_notifications is False
        assert preference.push_notifications is False

    def test_user_preference_entity_different_languages(self):
        """Test various language preferences."""
        languages = ["en", "es", "fr", "de", "ja", "zh"]

        for lang in languages:
            preference = UserPreferenceEntity(
                id=1,
                user_id=self.user_id,
                darkmode="light",
                language=lang,
                email_notifications=True,
                push_notifications=True,
                notifications_enabled=True,
            )

            assert preference.language == lang

    def test_user_preference_entity_is_frozen(self):
        """Verify that UserPreferenceEntity is immutable."""
        preference = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="dark",
            language="en",
            email_notifications=True,
            push_notifications=True,
            notifications_enabled=True,
        )

        with self.assertRaises(Exception):  # FrozenInstanceError
            preference.notifications_enabled = False

    def test_user_preference_entity_equality(self):
        """Two preferences with same data are equal."""
        pref1 = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="dark",
            language="en",
            email_notifications=True,
            push_notifications=True,
            notifications_enabled=True,
        )

        pref2 = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="dark",
            language="en",
            email_notifications=True,
            push_notifications=True,
            notifications_enabled=True,
        )

        assert pref1 == pref2

    def test_user_preference_entity_inequality(self):
        """Two preferences with different data are not equal."""
        pref1 = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="dark",
            language="en",
            email_notifications=True,
            push_notifications=True,
            notifications_enabled=True,
        )

        pref2 = UserPreferenceEntity(
            id=1,
            user_id=self.user_id,
            darkmode="light",  # Different
            language="en",
            email_notifications=True,
            push_notifications=True,
            notifications_enabled=True,
        )

        assert pref1 != pref2


class TestWorkspaceNotificationPreferenceEntity(unittest.TestCase):
    """Tests for WorkspaceNotificationPreferenceEntity."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_workspace_preference_entity_enabled(self):
        """Create enabled workspace notification preference."""
        preference = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        assert preference.id == 1
        assert preference.user_id == self.user_id
        assert preference.workspace_id == self.workspace_id
        assert preference.is_enabled is True
        assert preference.created_at == self.now
        assert preference.updated_at == self.now

    def test_workspace_preference_entity_disabled(self):
        """Create disabled workspace notification preference."""
        preference = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=False,
            created_at=self.now,
            updated_at=self.now,
        )

        assert preference.is_enabled is False

    def test_workspace_preference_entity_updated_after_created(self):
        """Updated_at should be after or equal to created_at."""
        created_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        updated_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        preference = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=True,
            created_at=created_time,
            updated_at=updated_time,
        )

        assert preference.updated_at >= preference.created_at

    def test_workspace_preference_entity_is_frozen(self):
        """Verify that WorkspaceNotificationPreferenceEntity is immutable."""
        preference = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        with self.assertRaises(Exception):  # FrozenInstanceError
            preference.is_enabled = False

    def test_workspace_preference_entity_equality(self):
        """Two workspace preferences with same data are equal."""
        pref1 = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        pref2 = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        assert pref1 == pref2

    def test_workspace_preference_entity_inequality_by_enabled(self):
        """Two workspace preferences with different enabled status are not equal."""
        pref1 = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        pref2 = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            is_enabled=False,  # Different
            created_at=self.now,
            updated_at=self.now,
        )

        assert pref1 != pref2


class TestAINotificationPreferenceEntity(unittest.TestCase):
    """Tests for AINotificationPreferenceEntity."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.workspace_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_ai_preference_entity_all_channels(self):
        """Test AI preference for all supported channels."""
        channels = [
            "general",
            "teammate_status",
            "action_created",
            "action_auto_executed",
            "action_error",
            "report_generated",
        ]

        for channel in channels:
            preference = AINotificationPreferenceEntity(
                id=1,
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                channel=channel,
                is_enabled=True,
                created_at=self.now,
                updated_at=self.now,
            )

            assert preference.channel == channel

    def test_ai_preference_entity_enabled(self):
        """Create enabled AI notification preference."""
        preference = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="general",
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        assert preference.id == 1
        assert preference.user_id == self.user_id
        assert preference.workspace_id == self.workspace_id
        assert preference.channel == "general"
        assert preference.is_enabled is True
        assert preference.created_at == self.now
        assert preference.updated_at == self.now

    def test_ai_preference_entity_disabled(self):
        """Create disabled AI notification preference."""
        preference = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="action_error",
            is_enabled=False,
            created_at=self.now,
            updated_at=self.now,
        )

        assert preference.is_enabled is False

    def test_ai_preference_entity_updated_timestamp(self):
        """Verify updated_at timestamp handling."""
        created_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        updated_time = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)

        preference = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="report_generated",
            is_enabled=True,
            created_at=created_time,
            updated_at=updated_time,
        )

        assert preference.updated_at > preference.created_at

    def test_ai_preference_entity_is_frozen(self):
        """Verify that AINotificationPreferenceEntity is immutable."""
        preference = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="general",
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        with self.assertRaises(Exception):  # FrozenInstanceError
            preference.is_enabled = False

    def test_ai_preference_entity_equality(self):
        """Two AI preferences with same data are equal."""
        pref1 = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="teammate_status",
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        pref2 = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="teammate_status",
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        assert pref1 == pref2

    def test_ai_preference_entity_inequality_by_channel(self):
        """Two AI preferences with different channels are not equal."""
        pref1 = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="action_created",
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        pref2 = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            channel="action_error",  # Different
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        assert pref1 != pref2


class TestPreferenceEntitiesWithMultipleUsers(unittest.TestCase):
    """Tests for preference entities with different users and workspaces."""

    def setUp(self):
        """Set up common test data."""
        self.user1_id = uuid4()
        self.user2_id = uuid4()
        self.workspace1_id = uuid4()
        self.workspace2_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_different_users_have_different_preferences(self):
        """Preferences for different users should be distinct."""
        pref1 = UserPreferenceEntity(
            id=1,
            user_id=self.user1_id,
            darkmode="dark",
            language="en",
            email_notifications=True,
            push_notifications=True,
            notifications_enabled=True,
        )

        pref2 = UserPreferenceEntity(
            id=2,
            user_id=self.user2_id,
            darkmode="light",
            language="es",
            email_notifications=False,
            push_notifications=False,
            notifications_enabled=False,
        )

        assert pref1 != pref2
        assert pref1.user_id != pref2.user_id

    def test_same_user_different_workspace_preferences(self):
        """Same user can have different preferences per workspace."""
        pref1 = WorkspaceNotificationPreferenceEntity(
            id=1,
            user_id=self.user1_id,
            workspace_id=self.workspace1_id,
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        pref2 = WorkspaceNotificationPreferenceEntity(
            id=2,
            user_id=self.user1_id,
            workspace_id=self.workspace2_id,
            is_enabled=False,
            created_at=self.now,
            updated_at=self.now,
        )

        assert pref1.user_id == pref2.user_id
        assert pref1.workspace_id != pref2.workspace_id
        assert pref1 != pref2

    def test_same_user_different_ai_channels(self):
        """Same user can have different AI preferences per channel."""
        pref1 = AINotificationPreferenceEntity(
            id=1,
            user_id=self.user1_id,
            workspace_id=self.workspace1_id,
            channel="general",
            is_enabled=True,
            created_at=self.now,
            updated_at=self.now,
        )

        pref2 = AINotificationPreferenceEntity(
            id=2,
            user_id=self.user1_id,
            workspace_id=self.workspace1_id,
            channel="action_error",
            is_enabled=False,
            created_at=self.now,
            updated_at=self.now,
        )

        assert pref1.user_id == pref2.user_id
        assert pref1.workspace_id == pref2.workspace_id
        assert pref1.channel != pref2.channel
        assert pref1 != pref2


if __name__ == "__main__":
    unittest.main()
