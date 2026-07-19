"""Input DTO for workflow graph validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidateWorkflowGraphRequest:
    """Input DTO for POST /api/workflows/validate endpoint (WorkflowViewSet.validate_graph).

    Used to validate a workflow graph definition without saving.
    """
    graph: dict[str, Any]
