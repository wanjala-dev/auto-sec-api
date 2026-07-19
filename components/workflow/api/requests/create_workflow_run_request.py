"""Input DTO for workflow run creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowRunTarget:
    """Target descriptor for workflow run."""
    target_type: str
    target_id: str | int


@dataclass(frozen=True)
class CreateWorkflowRunRequest:
    """Input DTO for POST /api/workflows/<id>/runs endpoint (WorkflowViewSet.runs).

    Used to trigger workflow execution on one or more targets.
    """
    workflow_id: str | int
    trigger_type: str
    targets: list[dict[str, Any]]
    trigger_payload: dict[str, Any] | None = None
    idempotency_key: str | None = None
