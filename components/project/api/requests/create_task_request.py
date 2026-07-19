"""Input DTO for task creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateTaskRequest:
    """Input DTO for POST /api/projects/ endpoint (ProjectView.post).

    Used to create a new task in a column.
    """
    title: str
    column: str | int
    project_id: str | int | None = None
    workspace_id: str | None = None
