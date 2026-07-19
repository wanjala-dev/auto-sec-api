"""Request DTO for workspace comment update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateCommentRequest:
    """Input DTO for PUT/PATCH /workspaces/comment/<id>/ endpoints.

    Handles workspace comment updates.
    """
    comment: str | None = None
    privacy: str | None = None
    tags: list[dict] | None = None
