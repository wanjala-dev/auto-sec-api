"""Notification domain entity — framework-free, immutable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class NotificationEntity:
    id: int
    recipient_id: UUID
    actor_id: UUID
    notification_type: str
    verb: str
    metadata: dict
    workspace_id: UUID | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime
    logo_url: str | None = None
    content_type_id: int | None = None
    object_id: str | None = None
