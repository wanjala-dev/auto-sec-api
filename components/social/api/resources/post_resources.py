"""Resource DTOs for post endpoints.

Output data classes for POST /social/ endpoints and GET responses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagResource:
    """Output DTO for tag data embedded in posts/comments."""
    id: str
    name: str


@dataclass(frozen=True)
class PostResource:
    """Output DTO for post detail endpoints."""
    id: str
    body: str
    created_on: str | None = None
    shared_on: str | None = None
    author: str | None = None
    shared_user: str | None = None
    likes: list[str] | None = None
    dislikes: list[str] | None = None
    tags: list[TagResource] | None = None
    shared_body: str | None = None


@dataclass(frozen=True)
class PostCollectionResource:
    """Output DTO for post list endpoints."""
    items: list[PostResource]
    count: int = 0
