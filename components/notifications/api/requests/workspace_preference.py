"""Request DTOs for workspace notification preference endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateWorkspaceNotificationPreferenceRequest:
    """Input DTO for POST /preferences/workspaces/ endpoint."""
    workspace: str
    is_enabled: bool = True


@dataclass(frozen=True)
class UpdateWorkspaceNotificationPreferenceRequest:
    """Input DTO for PATCH /preferences/workspaces/<workspace_id>/ endpoint."""
    is_enabled: bool
