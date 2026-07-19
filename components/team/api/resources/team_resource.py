"""Output DTOs for team endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeamResource:
    """Output DTO for team detail endpoints (GET /api/teams/<team_id>/)."""
    id: int | None = None
    workspace: str | int | None = None
    title: str | None = None
    kind: str | None = None
    members: list[dict[str, Any]] | None = None
    created_by: str | int | None = None
    created_at: str | None = None
    status: str | None = None
    privacy: str | None = None
    plan: str | int | None = None
    plan_id: int | None = None
    plan_end_date: str | None = None
    plan_status: str | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None


@dataclass(frozen=True)
class TeamSummaryResource:
    """Output DTO for lightweight team payload (login/user summary responses)."""
    id: int | None = None
    title: str | None = None
    kind: str | None = None
    status: str | None = None
    workspace_id: str | None = None
    plan_id: int | None = None
    plan_status: str | None = None
    plan_end_date: str | None = None


@dataclass(frozen=True)
class TeamCollectionResource:
    """Output DTO for team list endpoints (GET /api/teams/)."""
    items: list[TeamResource]
    count: int = 0
