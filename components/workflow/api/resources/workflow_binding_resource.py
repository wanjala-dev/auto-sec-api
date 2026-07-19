"""Output DTOs for workflow binding endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowBindingResource:
    """Output DTO for workflow binding detail endpoints (GET /api/workflow-bindings/<id>/)."""
    id: str | None = None
    workflow_id: str | None = None
    source_type: str | None = None
    source_id: str | int | None = None
    trigger_type: str | None = None
    config: dict[str, Any] | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class WorkflowBindingCollectionResource:
    """Output DTO for workflow binding list endpoints (GET /api/workflow-bindings/)."""
    items: list[WorkflowBindingResource]
    count: int = 0
