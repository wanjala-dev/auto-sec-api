"""ORM → domain entity mappers for the Notifications context."""

from __future__ import annotations

from uuid import UUID

from components.notifications.domain.entities.notification_entity import (
    NotificationEntity,
)
from components.notifications.domain.entities.preference_entity import (
    AINotificationPreferenceEntity,
    UserPreferenceEntity,
    WorkspaceNotificationPreferenceEntity,
)


def to_notification_entity(obj) -> NotificationEntity:
    return NotificationEntity(
        id=obj.id,
        recipient_id=UUID(str(obj.recipient_id)),
        actor_id=UUID(str(obj.actor_id)),
        notification_type=obj.notification_type,
        verb=obj.verb,
        metadata=obj.metadata or {},
        workspace_id=(
            UUID(str(obj.workspace_id)) if obj.workspace_id else None
        ),
        is_read=obj.is_read,
        read_at=obj.read_at,
        created_at=obj.created_at,
        logo_url=obj.logo_url,
        content_type_id=obj.content_type_id,
        object_id=obj.object_id,
    )


def to_user_preference_entity(obj) -> UserPreferenceEntity:
    return UserPreferenceEntity(
        id=obj.id,
        user_id=UUID(str(obj.user_id)),
        darkmode=obj.darkmode,
        language=obj.language or "",
        email_notifications=obj.email_notifications,
        push_notifications=obj.push_notifications,
        notifications_enabled=obj.notifications_enabled,
    )


def to_workspace_notification_preference_entity(
    obj,
) -> WorkspaceNotificationPreferenceEntity:
    return WorkspaceNotificationPreferenceEntity(
        id=obj.id,
        user_id=UUID(str(obj.user_id)),
        workspace_id=UUID(str(obj.workspace_id)),
        is_enabled=obj.is_enabled,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def to_ai_notification_preference_entity(
    obj,
) -> AINotificationPreferenceEntity:
    return AINotificationPreferenceEntity(
        id=obj.id,
        user_id=UUID(str(obj.user_id)),
        workspace_id=UUID(str(obj.workspace_id)),
        channel=obj.channel,
        is_enabled=obj.is_enabled,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )
