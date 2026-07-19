"""Input DTO for workflow enrollment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EnrollWorkflowRequest:
    """Input DTO for POST /api/workflows/<id>/enroll endpoint (WorkflowViewSet.enroll).

    Used to enroll targets in an automated workflow.
    """
    workflow_id: str | int
    targets: list[dict[str, Any]]
