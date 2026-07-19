"""Request DTO for workspace update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateWorkspaceRequest:
    """Input DTO for PUT/PATCH /workspaces/<id>/ endpoints.

    Handles workspace updates with partial field modification.
    """
    workspace_name: str | None = None
    workspace_story: str | None = None
    photo_url: str | None = None
    privacy: str | None = None
    tags: list[dict] | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None
    sector: str | None = None
    sector_ids: list[str] | None = None
    workspace_categories: list[int] | None = None
    is_verified: bool | None = None
    is_active: bool | None = None
    notifications_enabled: bool | None = None
