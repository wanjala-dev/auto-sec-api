"""Input DTO for workflow template creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CreateWorkflowTemplateRequest:
    """Input DTO for POST /api/workflow-templates/ endpoint (WorkflowTemplateViewSet.create).

    Used to create a reusable workflow template.
    """
    label: str
    description: str | None = None
    category: str | None = None
    workspace_id: str | int | None = None
    default_graph: dict[str, Any] | None = None
    version: int | None = None
