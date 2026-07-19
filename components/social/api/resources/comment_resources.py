"""Resource DTOs for comment endpoints.

Output data classes for POST/GET /social/comment endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommentResource:
    """Output DTO for comment detail endpoints."""
    id: str
    comment: str
    created_on: str | None = None
    author: str | None = None
    post: str | None = None
    parent: str | None = None
    likes: list[str] | None = None
    dislikes: list[str] | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class CommentCollectionResource:
    """Output DTO for comment list endpoints."""
    items: list[CommentResource]
    count: int = 0
