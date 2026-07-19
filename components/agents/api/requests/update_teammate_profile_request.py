"""Request DTO for PATCH /ai/agents/teammate/<id>/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateTeammateProfileRequest:
    """Input DTO for PATCH /ai/agents/teammate/<id>/ endpoint.

    Updates a teammate's profile display name and/or avatar in a
    workspace. ``avatar_url=None`` leaves the avatar untouched; ""
    clears it back to the platform default.
    """
    display_name: str | None = None
    avatar_url: str | None = None
