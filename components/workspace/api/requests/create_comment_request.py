"""Request DTO for workspace comment creation endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateCommentRequest:
    """Input DTO for POST /workspaces/comment/create endpoint.

    Handles workspace comment creation with optional privacy settings and parent references.
    """
    comment: str
    workspace: str
    privacy: str | None = None
    parent: int | None = None
    tags: list[dict] | None = None
