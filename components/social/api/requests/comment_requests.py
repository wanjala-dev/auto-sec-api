"""Request DTOs for comment endpoints.

Input data classes for POST /social/comment and related endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateCommentRequest:
    """Input DTO for POST /social/comment endpoint."""
    comment: str
    post: str
    author: str | None = None
    parent: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class UpdateCommentRequest:
    """Input DTO for PUT/PATCH /social/comment/<id>/ endpoint."""
    comment: str | None = None
    parent: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class CreateCommentReplyRequest:
    """Input DTO for POST /social/<post_id>/comment/<comment_id>/reply endpoint."""
    comment: str
    parent: str | None = None
    author: str | None = None
