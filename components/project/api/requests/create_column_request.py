"""Input DTO for column creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateColumnRequest:
    """Input DTO for POST /api/projects/columns/ endpoint (ColumnsView.post).

    Used to create a new column (kanban board column) within a project.
    """
    team: str | int
    workspace: str | int
    title: str | None = None
    project: str | int | None = None
    order: int | None = None
