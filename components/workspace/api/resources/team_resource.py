"""Resource DTO for team entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamResource:
    """Output DTO for team endpoints.

    Represents a team within a workspace.
    """
    id: int | None = None
    name: str | None = None
    workspace: str | None = None
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    members: list[dict] | None = None
    projects: list[dict] | None = None


@dataclass(frozen=True)
class TeamCollectionResource:
    """Output DTO for team list endpoints.

    Represents a collection of teams.
    """
    items: list[TeamResource] | None = None
    count: int = 0
