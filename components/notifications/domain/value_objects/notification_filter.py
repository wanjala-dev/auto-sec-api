"""Notification filter value object — encapsulates query criteria.

Replaces the inline query-param parsing scattered across the controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class NotificationFilter:
    """Immutable specification for notification search criteria."""

    user_id: UUID
    is_read: bool | None = None
    notification_type: str | None = None
    workspace_id: UUID | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    period: str | None = None  # "today", "last_7_days", "last_30_days"
