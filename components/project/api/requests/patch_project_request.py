"""Input DTO for project updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatchProjectRequest:
    """Input DTO for PATCH /api/projects/patch/<project_id>/ endpoint (ProjectPatchView.patch).

    Used to partially update project properties.
    """
    project_id: str | int
    title: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    lead: str | int | None = None
    priority: str | None = None
    status: str | None = None
    resources: Any = None
    bgColor: str | None = None
    budget: str | int | None = None
    updates: list[int] | None = None
    milestones: list[int] | None = None
    contribution_means: list[int] | None = None
