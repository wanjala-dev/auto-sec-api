"""Output DTOs for workflow template endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowTemplateResource:
    """Output DTO for workflow template detail endpoints (GET /api/workflow-templates/<id>/)."""
    id: str | None = None
    workspace_id: str | None = None
    label: str | None = None
    description: str | None = None
    category: str | None = None
    version: int | None = None
    is_system: bool | None = None
    default_graph: dict[str, Any] | None = None
    suggested_trigger_ids: list[str] | None = None
    supports_ai_nodes: bool | None = None
    created_by: str | int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class WorkflowTemplateCollectionResource:
    """Output DTO for workflow template list endpoints (GET /api/workflow-templates/)."""
    items: list[WorkflowTemplateResource]
    count: int = 0
