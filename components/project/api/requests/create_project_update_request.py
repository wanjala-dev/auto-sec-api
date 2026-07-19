"""Input DTO for project update creation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CreateProjectUpdateRequest:
    """Input DTO for POST /api/projects/updates/ endpoint (ProjectUpdatesView.post).

    Used to create a new update entry for a project.
    """
    project: str | int | None = None
    Project: str | int | None = None
    Update: str | None = None
    privacy: str | None = None
    tags: list[int] | None = None
