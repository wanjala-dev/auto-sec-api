"""Request DTO for workspace creation endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateWorkspaceRequest:
    """Input DTO for POST /workspaces/create/ endpoint.

    Handles workspace creation with sector, category, and tag assignments.
    """
    workspace_name: str
    workspace_owner: str | None = None
    sector: str | None = None
    sector_ids: list[str] | None = None
    workspace_story: str | None = None
    photo_url: str | None = None
    privacy: str | None = None
    tags: list[dict] | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None
    workspace_categories: list[int] | None = None
    workspace_subcategories: list[int] | None = None
    is_verified: bool = False
    is_active: bool = True
    notifications_enabled: bool = True
    ai_teammate_enabled: bool = False
