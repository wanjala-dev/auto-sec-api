"""Input DTO for milestone creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateMilestoneRequest:
    """Input DTO for POST /api/projects/milestones/ endpoint (MilestonesView.post).

    Used to create a new milestone for a project.
    """
    project_id: str | int
    name: str
    description: str | None = None
    target_date: str | None = None
