"""Request DTOs for comment endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateCommentRequest:
    """Input DTO for POST /comments/ endpoint."""
    content: str
    news: str


@dataclass(frozen=True)
class CreateCommentReplyRequest:
    """Input DTO for POST /comments/<comment_id>/reply/ endpoint."""
    content: str
    parent_id: int | None = None
