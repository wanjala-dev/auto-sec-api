"""Input DTO for workflow binding creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CreateWorkflowBindingRequest:
    """Input DTO for POST /api/workflow-bindings/ endpoint (WorkflowBindingViewSet.create).

    Used to bind a workflow to a feature event trigger.
    """
    workflow_id: str | int
    source_type: str
    source_id: str | int
    trigger_type: str | None = None
    config: dict[str, Any] | None = None
