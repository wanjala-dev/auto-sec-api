"""Input DTO for project creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateProjectRequest:
    """Input DTO for POST /api/projects/ endpoint (ProjectsView.post).

    Used to create a new project within a team.
    """
    title: str
    team: str | int
    workspace_id: str | None = None
