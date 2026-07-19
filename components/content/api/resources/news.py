"""Resource DTOs for news articles endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserSummary:
    """User information embedded in news resource."""
    id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True)
class FileResource:
    """File information embedded in news resource."""
    id: str
    name: str
    file_url: str | None = None


@dataclass(frozen=True)
class TagResource:
    """Tag information embedded in news resource."""
    id: int
    name: str


@dataclass(frozen=True)
class CommentResource:
    """Comment information embedded in news resource."""
    id: int
    content: str
    author: UserSummary
    parent: int | None = None
    date_posted: str | None = None


@dataclass(frozen=True)
class NewsResource:
    """Output DTO for news detail endpoints."""
    id: str
    title: str
    excerpt: str
    body: str
    image: str
    workspace: str
    author: UserSummary
    category: str | None = None
    featured: bool = False
    slug: str | None = None
    status: int | None = None
    pub_date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    tags: list[TagResource] | None = None
    media: list[FileResource] | None = None
    workspace_comments: list[CommentResource] | None = None


@dataclass(frozen=True)
class NewsCollectionResource:
    """Output DTO for news list endpoint."""
    items: list[NewsResource]
    count: int = 0
