"""Input DTOs for workflow run control actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CancelWorkflowRunRequest:
    """Input DTO for POST /api/workflow-runs/<id>/cancel endpoint."""
    run_id: str | int


@dataclass(frozen=True)
class RetryWorkflowRunRequest:
    """Input DTO for POST /api/workflow-runs/<id>/retry endpoint."""
    run_id: str | int


@dataclass(frozen=True)
class PauseWorkflowRunRequest:
    """Input DTO for POST /api/workflow-runs/<id>/pause endpoint."""
    run_id: str | int


@dataclass(frozen=True)
class ResumeWorkflowRunRequest:
    """Input DTO for POST /api/workflow-runs/<id>/resume endpoint."""
    run_id: str | int


@dataclass(frozen=True)
class CompleteWorkflowStepRequest:
    """Input DTO for POST /api/workflow-runs/<id>/steps/<node_id>/complete endpoint."""
    run_id: str | int
    node_id: str
    output: dict[str, Any] | None = None


@dataclass(frozen=True)
class InputWorkflowStepRequest:
    """Input DTO for POST /api/workflow-runs/<id>/steps/<node_id>/input endpoint."""
    run_id: str | int
    node_id: str
    input: dict[str, Any] | None = None
