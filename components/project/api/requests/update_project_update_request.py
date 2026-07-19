"""Input DTO for project update edits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateProjectUpdateRequest:
    """Input DTO for PUT /api/projects/updates/<update_id>/ endpoint (ProjectUpdatesView.put).

    Used to update an existing project update entry.
    """
    update_id: str | int
    Update: str | None = None
    privacy: str | None = None
    tags: list[int] | None = None
