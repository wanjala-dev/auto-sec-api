"""Resource DTO for contribution means entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContributionMeansResource:
    """Output DTO for contribution means detail endpoints.

    Represents a contribution means (e.g., donation method) available for workspaces.
    """
    id: int | None = None
    name: str | None = None
    icon: str | None = None
    description: str | None = None
    is_active: bool = True
    order: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    workspaces: list[dict] | None = None
    projects: list[dict] | None = None
    tasks: list[dict] | None = None
    recipients: list[dict] | None = None


@dataclass(frozen=True)
class ContributionMeansCollectionResource:
    """Output DTO for contribution means list endpoints.

    Represents a collection of contribution means.
    """
    items: list[ContributionMeansResource] | None = None
    count: int = 0
