"""Request DTOs for news articles endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateNewsRequest:
    """Input DTO for POST /news/add/ endpoint."""
    title: str
    excerpt: str
    body: str
    image: str
    workspace_id: str
    category: str | None = None
    pub_date: str | None = None
    featured: bool = False
    slug: str | None = None
    status: int | None = None


@dataclass(frozen=True)
class UpdateNewsRequest:
    """Input DTO for PUT /news/ endpoint."""
    title: str
    excerpt: str
    body: str
    image: str
    category: str | None = None
    pub_date: str | None = None
    featured: bool = False
    slug: str | None = None
    status: int | None = None
