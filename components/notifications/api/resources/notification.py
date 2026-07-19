"""Resource DTOs for notification endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserSummary:
    """User information embedded in notification resource."""
    id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None
    avatar: str | None = None


@dataclass(frozen=True)
class WorkspaceSummary:
    """Workspace information embedded in notification resource."""
    id: str
    name: str


@dataclass(frozen=True)
class TargetObject:
    """Target object information embedded in notification resource."""
    id: str | int
    type: str
    app_label: str
    representation: str | None = None


@dataclass(frozen=True)
class NotificationResource:
    """Output DTO for notification detail endpoints."""
    id: int
    verb: str
    notification_type: str
    actor: UserSummary
    recipient: UserSummary
    is_read: bool
    metadata: dict | None = None
    logo_url: str | None = None
    content_type: str | None = None
    object_id: str | int | None = None
    target: TargetObject | None = None
    workspace: WorkspaceSummary | None = None
    created_at: str | None = None
    updated_at: str | None = None
    read_at: str | None = None


@dataclass(frozen=True)
class NotificationCollectionResource:
    """Output DTO for notification list endpoint."""
    items: list[NotificationResource]
    count: int = 0


@dataclass(frozen=True)
class UnreadCountResource:
    """Output DTO for unread count endpoint."""
    count: int = 0


@dataclass(frozen=True)
class MarkAllReadResponse:
    """Output DTO for mark all read endpoint."""
    updated: int = 0
