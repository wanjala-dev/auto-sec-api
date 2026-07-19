"""Input DTO for task updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, dict


@dataclass(frozen=True)
class UpdateTaskRequest:
    """Input DTO for PATCH /api/projects/task/update/<uuid>/<task_id>/ endpoint (TaskDetailView.patch).

    Used to update task properties such as title, status, assignments, etc.
    The data field captures all updateable properties dynamically.
    """
    task_id: str | int
    data: dict[str, Any]
