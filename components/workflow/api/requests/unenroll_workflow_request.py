"""Input DTO for workflow unenrollment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UnenrollWorkflowRequest:
    """Input DTO for POST /api/workflows/<id>/unenroll endpoint (WorkflowViewSet.unenroll).

    Used to unenroll targets from an automated workflow.
    """
    workflow_id: str | int
    targets: list[dict[str, Any]]
