"""Input DTO for workflow updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UpdateWorkflowRequest:
    """Input DTO for PUT /api/workflows/<id>/ endpoint (WorkflowViewSet.update).

    Used to fully update a workflow.
    """
    workflow_id: str | int
    name: str | None = None
    description: str | None = None
    goal: str | None = None
    status: str | None = None
    graph: dict[str, Any] | None = None
    template_id: str | None = None
