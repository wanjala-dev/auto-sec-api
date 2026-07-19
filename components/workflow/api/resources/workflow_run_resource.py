"""Output DTOs for workflow run endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowRunResource:
    """Output DTO for workflow run detail endpoints (GET /api/workflow-runs/<id>/)."""
    id: str | None = None
    workflow_id: str | None = None
    workflow_version: int | None = None
    status: str | None = None
    trigger_type: str | None = None
    trigger_payload: dict[str, Any] | None = None
    target_type: str | None = None
    target_id: str | int | None = None
    current_node_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    canceled_at: str | None = None
    paused_at: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class WorkflowRunCollectionResource:
    """Output DTO for workflow run list endpoints (GET /api/workflows/<id>/runs/)."""
    items: list[WorkflowRunResource]
    count: int = 0
