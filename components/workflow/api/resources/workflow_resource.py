"""Output DTOs for workflow endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowResource:
    """Output DTO for workflow detail endpoints (GET /api/workflows/<id>/)."""
    id: str | None = None
    workspace_id: str | None = None
    name: str | None = None
    description: str | None = None
    goal: str | None = None
    template_id: str | None = None
    is_custom: bool | None = None
    status: str | None = None
    version: int | None = None
    graph: dict[str, Any] | None = None
    created_by: str | int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class WorkflowSummaryResource:
    """Output DTO for workflow list endpoints (GET /api/workflows/)."""
    id: str | None = None
    name: str | None = None
    status: str | None = None
    goal: str | None = None
    template_id: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class WorkflowCollectionResource:
    """Output DTO for workflow list endpoints."""
    items: list[WorkflowResource | WorkflowSummaryResource]
    count: int = 0
