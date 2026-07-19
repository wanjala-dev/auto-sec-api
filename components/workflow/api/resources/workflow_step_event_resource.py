"""Output DTOs for workflow step event endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowStepEventResource:
    """Output DTO for workflow step event detail endpoints (GET /api/workflow-runs/<id>/events/<event_id>/)."""
    id: str | None = None
    run_id: str | None = None
    node_id: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class WorkflowStepEventCollectionResource:
    """Output DTO for workflow step event list endpoints (GET /api/workflow-runs/<id>/events/)."""
    items: list[WorkflowStepEventResource]
    count: int = 0
