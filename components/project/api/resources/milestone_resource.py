"""Output DTOs for milestone endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MilestoneResource:
    """Output DTO for milestone detail endpoints (GET /api/projects/milestones/<milestone_id>/)."""
    id: int | None = None
    name: str | None = None
    description: str | None = None
    target_date: str | None = None
    creator: dict[str, str] | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class MilestoneCollectionResource:
    """Output DTO for milestone list endpoints (GET /api/projects/milestones/)."""
    items: list[MilestoneResource]
    count: int = 0
