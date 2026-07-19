"""Output DTOs for task comment endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskCommentResource:
    """Output DTO for task comment detail endpoints (GET /api/projects/tasks/<task_id>/comments/<comment_id>/)."""
    id: int | None = None
    comment: str | None = None
    created_on: str | None = None
    author: dict[str, Any] | None = None
    task_id: int | None = None
    parent: int | None = None
    recipients: list[dict[str, Any]] | None = None
    likes: list[dict[str, Any]] | None = None
    dislikes: list[dict[str, Any]] | None = None
    tags: list[dict[str, Any]] | None = None
    is_parent: bool | None = None


@dataclass(frozen=True)
class TaskCommentCollectionResource:
    """Output DTO for task comment list endpoints (GET /api/projects/tasks/<task_id>/comments/)."""
    items: list[TaskCommentResource]
    count: int = 0
