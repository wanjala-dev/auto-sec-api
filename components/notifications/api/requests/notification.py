"""Request DTOs for notification endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarkNotificationReadRequest:
    """Input DTO for POST /notifications/<id>/mark_read/ endpoint."""
    is_read: bool = True


@dataclass(frozen=True)
class MarkAllNotificationsReadRequest:
    """Input DTO for POST /notifications/mark_all_read/ endpoint."""
    workspace_id: str | None = None
