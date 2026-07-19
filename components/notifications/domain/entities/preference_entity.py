"""User and workspace notification preference entities — framework-free."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class UserPreferenceEntity:
    id: int
    user_id: UUID
    darkmode: str
    language: str
    email_notifications: bool
    push_notifications: bool
    notifications_enabled: bool


@dataclass(frozen=True)
class WorkspaceNotificationPreferenceEntity:
    id: int
    user_id: UUID
    workspace_id: UUID
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AINotificationPreferenceEntity:
    id: int
    user_id: UUID
    workspace_id: UUID
    channel: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
