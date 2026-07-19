"""Output DTOs for project endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectResource:
    """Output DTO for project detail endpoints (GET /api/projects/<project_id>/)."""
    pk: int | None = None
    id: int | None = None
    team: str | int | None = None
    created_by: str | int | None = None
    lead: str | int | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    created_at: str | None = None
    priority: str | None = None
    status: str | None = None
    registered_time: int | None = None
    resources: Any = None
    description: str | None = None
    num_tasks_todo: int | None = None
    milestones: list[dict[str, Any]] | None = None
    updates: list[dict[str, Any]] | None = None
    bgColor: str | None = None
    budget: dict[str, Any] | None = None
    budget_estimates: list[dict[str, Any]] | None = None
    budget_estimates_total: float | None = None
    contribution_means: list[dict[str, Any]] | None = None
    tasks: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ProjectCollectionResource:
    """Output DTO for project list endpoints (GET /api/projects/)."""
    items: list[ProjectResource]
    count: int = 0
