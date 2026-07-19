"""Input DTO for task user assignments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssignUsersToTaskRequest:
    """Input DTO for PATCH /api/projects/tasks/<task_id>/assign/ endpoint (AssignUsersToTaskView.patch).

    Used to assign multiple users to a task.
    """
    task_id: str | int
    user_ids: list[str | int]
