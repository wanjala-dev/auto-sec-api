"""Output DTOs for task endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskResource:
    """Output DTO for task detail endpoints (GET /api/projects/task/<task_id>/)."""
    id: int | None = None
    pk: int | None = None
    title: str | None = None
    status: str | None = None
    order: int | None = None
    due_date: str | None = None
    is_completed: bool | None = None
    column: dict[str, Any] | None = None
    assigned_to: list[dict[str, Any]] | None = None
    project: int | None = None
    team: int | None = None
    workspace: str | None = None
    created_at: str | None = None
    created_by: str | int | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class TaskCollectionResource:
    """Output DTO for task list endpoints (GET /api/projects/tasks/)."""
    items: list[TaskResource]
    count: int = 0
