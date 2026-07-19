"""Input DTO for task comment creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateTaskCommentRequest:
    """Input DTO for POST /api/projects/tasks/<task_id>/comments/ endpoint (TaskCommentListCreateView.post).

    Used to create a new comment on a task.
    """
    task_id: str | int
    comment: str
    parent: str | int | None = None
