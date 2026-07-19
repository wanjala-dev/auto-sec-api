"""Input DTO for milestone updates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateMilestoneRequest:
    """Input DTO for PUT /api/projects/milestones/<milestone_id>/ endpoint (MilestonesView.put).

    Used to update a milestone.
    """
    milestone_id: str | int
    name: str | None = None
    description: str | None = None
    target_date: str | None = None
