"""Resource DTO for workspace entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceResource:
    """Output DTO for workspace detail endpoints.

    Represents a single workspace with all its properties.
    """
    id: str
    workspace_name: str
    workspace_owner: str | None = None
    sector: dict | None = None
    sectors: list[dict] | None = None
    sector_ids: list[str] | None = None
    is_verified: bool = False
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
    workspace_story: str | None = None
    photo_url: str | None = None
    privacy: str | None = None
    tags: list[dict] | None = None
    followers: list[dict] | None = None
    operations: list[dict] | None = None
    workspace_categories: list[dict] | None = None
    workspace_subcategories: list[int] | None = None
    start_date: str | None = None
    end_date: str | None = None
    status: str | None = None
    plan: dict | None = None
    associated_users: list[dict] | None = None
    contribution_means: list[dict] | None = None
    budgets: list[dict] | None = None
    ai_teammate_display_name: str | None = None
    ai_teammate_enabled: bool = False
    orchestrator_enabled: bool = False
    notifications_enabled: bool = True
    teams: list[dict] | None = None
    projects: list[dict] | None = None
    transaction_categories: list[dict] | None = None


@dataclass(frozen=True)
class WorkspaceCollectionResource:
    """Output DTO for workspace list endpoints.

    Represents a paginated collection of workspaces.
    """
    items: list[WorkspaceResource] | None = None
    count: int = 0
