"""Resource DTOs for workspace notification preference endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceSummary:
    """Workspace information embedded in preference resource."""
    id: str
    name: str | None = None


@dataclass(frozen=True)
class WorkspaceNotificationPreferenceResource:
    """Output DTO for workspace notification preference detail endpoints."""
    id: int
    workspace: str | WorkspaceSummary
    is_enabled: bool
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class WorkspaceNotificationPreferenceCollectionResource:
    """Output DTO for workspace notification preference list endpoint."""
    items: list[WorkspaceNotificationPreferenceResource]
    count: int = 0
