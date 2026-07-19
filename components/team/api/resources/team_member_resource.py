"""Output DTOs for team member endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeamMemberResource:
    """Output DTO for team member detail."""
    id: str | int | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_staff: bool | None = None
    is_active: bool | None = None
    avatar_url: str | None = None
    teams: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class TeamMemberCollectionResource:
    """Output DTO for team member list endpoints (GET /api/teams/members/)."""
    items: list[TeamMemberResource]
    count: int = 0
    results: list[dict[str, Any]] | None = None
