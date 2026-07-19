"""Output DTOs for project update endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectUpdateResource:
    """Output DTO for project update detail endpoints (GET /api/projects/updates/<update_id>/)."""
    id: int | None = None
    Update: str | None = None
    workspace: str | None = None
    project: int | None = None
    Project: int | None = None
    created_on: str | None = None
    author: str | int | None = None
    likes: list[str | int] | None = None
    privacy: str | None = None
    dislikes: list[str | int] | None = None
    parent: int | None = None
    tags: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ProjectUpdateCollectionResource:
    """Output DTO for project update list endpoints (GET /api/projects/updates/)."""
    items: list[ProjectUpdateResource]
    count: int = 0
