"""Resource DTOs for AI notification preference endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceSummary:
    """Workspace information embedded in preference resource."""
    id: str
    name: str | None = None


@dataclass(frozen=True)
class AINotificationPreferenceResource:
    """Output DTO for AI notification preference detail endpoints."""
    id: int
    workspace: str | WorkspaceSummary
    channel: str
    is_enabled: bool
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class AINotificationPreferenceCollectionResource:
    """Output DTO for AI notification preference list endpoint."""
    items: list[AINotificationPreferenceResource]
    count: int = 0
