"""Resource DTO for workspace comment entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommentResource:
    """Output DTO for workspace comment detail endpoints.

    Represents a single workspace comment with author and engagement metrics.
    """
    pk: int | None = None
    comment: str | None = None
    workspace: str | None = None
    privacy: str | None = None
    created_on: str | None = None
    author: dict | None = None
    likes: list[dict] | None = None
    dislikes: list[dict] | None = None
    parent: int | None = None
    tags: list[dict] | None = None


@dataclass(frozen=True)
class CommentCollectionResource:
    """Output DTO for workspace comment list endpoints.

    Represents a collection of workspace comments.
    """
    items: list[CommentResource] | None = None
    count: int = 0
