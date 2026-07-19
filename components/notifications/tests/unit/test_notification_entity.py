"""Unit tests for NotificationEntity domain entity."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import unittest

from components.notifications.domain.entities.notification_entity import (
    NotificationEntity,
)


class TestNotificationEntityConstruction(unittest.TestCase):
    """Tests for NotificationEntity instantiation and immutability."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.recipient_id = uuid4()
        self.actor_id = uuid4()
        self.workspace_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_notification_entity_with_all_fields(self):
        """Create a notification entity with all fields populated."""
        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={"post_id": 42, "post_title": "Great post"},
            workspace_id=self.workspace_id,
            is_read=False,
            read_at=None,
            created_at=self.now,
            logo_url="https://example.com/logo.png",
            content_type_id=5,
            object_id="post_42",
        )

        assert notification.id == 1
        assert notification.recipient_id == self.recipient_id
        assert notification.actor_id == self.actor_id
        assert notification.notification_type == "like"
        assert notification.verb == "liked"
        assert notification.metadata == {"post_id": 42, "post_title": "Great post"}
        assert notification.workspace_id == self.workspace_id
        assert notification.is_read is False
        assert notification.read_at is None
        assert notification.created_at == self.now
        assert notification.logo_url == "https://example.com/logo.png"
        assert notification.content_type_id == 5
        assert notification.object_id == "post_42"

    def test_notification_entity_minimal_fields(self):
        """Create a notification entity with only required fields."""
        notification = NotificationEntity(
            id=42,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="comment",
            verb="commented",
            metadata={},
            workspace_id=None,
            is_read=True,
            read_at=self.now,
            created_at=self.now,
        )

        assert notification.id == 42
        assert notification.logo_url is None
        assert notification.content_type_id is None
        assert notification.object_id is None

    def test_notification_entity_is_frozen(self):
        """Verify that NotificationEntity is immutable."""
        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="mention",
            verb="mentioned",
            metadata={},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        with self.assertRaises(Exception):  # FrozenInstanceError
            notification.is_read = True

    def test_notification_entity_with_complex_metadata(self):
        """Test notification with complex nested metadata."""
        complex_metadata = {
            "post_id": 123,
            "post_title": "Breaking news",
            "author": {
                "id": "user_456",
                "name": "John Doe",
                "avatar": "https://example.com/avatar.jpg",
            },
            "tags": ["urgent", "important"],
            "engagement_count": 42,
        }

        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="system",
            verb="triggered",
            metadata=complex_metadata,
            workspace_id=self.workspace_id,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification.metadata == complex_metadata
        assert notification.metadata["author"]["name"] == "John Doe"
        assert "urgent" in notification.metadata["tags"]

    def test_notification_entity_with_empty_metadata(self):
        """Test notification with empty metadata dictionary."""
        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="follow",
            verb="followed",
            metadata={},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification.metadata == {}
        assert len(notification.metadata) == 0


class TestNotificationEntityReadState(unittest.TestCase):
    """Tests for notification read state and read_at timestamp."""

    def setUp(self):
        """Set up common test data."""
        self.user_id = uuid4()
        self.recipient_id = uuid4()
        self.actor_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_unread_notification_has_no_read_at(self):
        """Unread notification should have read_at as None."""
        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification.is_read is False
        assert notification.read_at is None

    def test_read_notification_has_read_at(self):
        """Read notification should have read_at timestamp."""
        read_time = datetime.now(timezone.utc)
        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={},
            workspace_id=None,
            is_read=True,
            read_at=read_time,
            created_at=self.now,
        )

        assert notification.is_read is True
        assert notification.read_at == read_time

    def test_read_at_is_after_created_at(self):
        """read_at should be after created_at for valid notifications."""
        created_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        read_time = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={},
            workspace_id=None,
            is_read=True,
            read_at=read_time,
            created_at=created_time,
        )

        assert notification.read_at > notification.created_at


class TestNotificationEntityWorkspaceContext(unittest.TestCase):
    """Tests for workspace-related notification properties."""

    def setUp(self):
        """Set up common test data."""
        self.recipient_id = uuid4()
        self.actor_id = uuid4()
        self.workspace_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_notification_with_workspace_id(self):
        """Notification can be associated with a specific workspace."""
        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="comment",
            verb="commented",
            metadata={},
            workspace_id=self.workspace_id,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification.workspace_id == self.workspace_id
        assert notification.workspace_id is not None

    def test_notification_without_workspace_id(self):
        """Notification can be workspace-agnostic (system notification)."""
        notification = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="system",
            verb="triggered",
            metadata={},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification.workspace_id is None


class TestNotificationEntityTypes(unittest.TestCase):
    """Tests for notification type and verb fields."""

    def setUp(self):
        """Set up common test data."""
        self.recipient_id = uuid4()
        self.actor_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_notification_types(self):
        """Test various notification types."""
        types_and_verbs = [
            ("like", "liked"),
            ("comment", "commented"),
            ("follow", "followed"),
            ("mention", "mentioned"),
            ("message", "sent"),
            ("system", "triggered"),
            ("ai_event", "executed"),
            ("report", "generated"),
        ]

        for notification_type, verb in types_and_verbs:
            notification = NotificationEntity(
                id=1,
                recipient_id=self.recipient_id,
                actor_id=self.actor_id,
                notification_type=notification_type,
                verb=verb,
                metadata={},
                workspace_id=None,
                is_read=False,
                read_at=None,
                created_at=self.now,
            )

            assert notification.notification_type == notification_type
            assert notification.verb == verb


class TestNotificationEntityActorRecipient(unittest.TestCase):
    """Tests for actor and recipient identification."""

    def setUp(self):
        """Set up common test data."""
        self.now = datetime.now(timezone.utc)

    def test_actor_and_recipient_are_different_users(self):
        """Actor and recipient should be different UUIDs for normal notifications."""
        actor_id = uuid4()
        recipient_id = uuid4()

        notification = NotificationEntity(
            id=1,
            recipient_id=recipient_id,
            actor_id=actor_id,
            notification_type="like",
            verb="liked",
            metadata={},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification.actor_id != notification.recipient_id
        assert notification.actor_id == actor_id
        assert notification.recipient_id == recipient_id

    def test_actor_and_recipient_same_for_system_notification(self):
        """System notifications might have actor_id == recipient_id."""
        user_id = uuid4()

        notification = NotificationEntity(
            id=1,
            recipient_id=user_id,
            actor_id=user_id,
            notification_type="system",
            verb="triggered",
            metadata={"reason": "account_upgrade"},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification.actor_id == notification.recipient_id


class TestNotificationEntityDataIntegrity(unittest.TestCase):
    """Tests for data integrity and consistency."""

    def setUp(self):
        """Set up common test data."""
        self.recipient_id = uuid4()
        self.actor_id = uuid4()
        self.now = datetime.now(timezone.utc)

    def test_notification_fields_preserved_through_access(self):
        """Verify all fields are preserved and accessible."""
        notification = NotificationEntity(
            id=999,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="mention",
            verb="mentioned",
            metadata={"context": "reply"},
            workspace_id=uuid4(),
            is_read=True,
            read_at=self.now,
            created_at=self.now,
            logo_url="https://example.com/logo.png",
            content_type_id=42,
            object_id="obj_123",
        )

        # Access all fields to verify they're accessible
        assert notification.id == 999
        assert notification.recipient_id == self.recipient_id
        assert notification.actor_id == self.actor_id
        assert notification.notification_type == "mention"
        assert notification.verb == "mentioned"
        assert notification.metadata == {"context": "reply"}
        assert notification.workspace_id is not None
        assert notification.is_read is True
        assert notification.read_at == self.now
        assert notification.created_at == self.now
        assert notification.logo_url == "https://example.com/logo.png"
        assert notification.content_type_id == 42
        assert notification.object_id == "obj_123"

    def test_notification_equality(self):
        """Two notifications with same data are equal."""
        notification1 = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={"count": 5},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        notification2 = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={"count": 5},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification1 == notification2

    def test_notification_inequality(self):
        """Two notifications with different data are not equal."""
        notification1 = NotificationEntity(
            id=1,
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        notification2 = NotificationEntity(
            id=2,  # Different ID
            recipient_id=self.recipient_id,
            actor_id=self.actor_id,
            notification_type="like",
            verb="liked",
            metadata={},
            workspace_id=None,
            is_read=False,
            read_at=None,
            created_at=self.now,
        )

        assert notification1 != notification2


if __name__ == "__main__":
    unittest.main()
