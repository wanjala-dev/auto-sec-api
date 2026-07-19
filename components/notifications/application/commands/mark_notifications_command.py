"""Command and result value objects for notification mark-read operations."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MarkNotificationReadCommand:
    notification_id: int
    user_id: UUID


@dataclass(frozen=True)
class MarkNotificationReadResult:
    success: bool
    notification_id: int


@dataclass(frozen=True)
class MarkAllNotificationsReadCommand:
    user_id: UUID
    workspace_id: UUID | None = None


@dataclass(frozen=True)
class MarkAllNotificationsReadResult:
    updated_count: int
