"""Resource DTOs for comment endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserSummary:
    """User information embedded in comment resource."""
    id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True)
class CommentResource:
    """Output DTO for comment detail endpoints."""
    id: int
    content: str
    author: UserSummary
    news: str | None = None
    parent: int | None = None
    date_posted: str | None = None


@dataclass(frozen=True)
class CommentCollectionResource:
    """Output DTO for comment list endpoint."""
    items: list[CommentResource]
    count: int = 0
