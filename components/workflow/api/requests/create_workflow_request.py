"""Input DTO for workflow creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CreateWorkflowRequest:
    """Input DTO for POST /api/workflows/ endpoint (WorkflowViewSet.create).

    Used to create a new workflow within a workspace.
    """
    workspace_id: str | int
    name: str
    description: str | None = None
    goal: str | None = None
    template_id: str | None = None
    is_custom: bool | None = None
    status: str | None = None
    graph: dict[str, Any] | None = None
