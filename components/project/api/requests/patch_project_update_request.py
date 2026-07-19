"""Input DTO for partial project update edits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PatchProjectUpdateRequest:
    """Input DTO for PATCH /api/projects/updates/<update_id>/ endpoint (ProjectUpdatesView.patch).

    Used to partially update a project update entry.
    """
    update_id: str | int
    Update: str | None = None
    privacy: str | None = None
    tags: list[int] | None = None
