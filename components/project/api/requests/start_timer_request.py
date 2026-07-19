"""Input DTO for timer operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StartTimerRequest:
    """Input DTO for POST /api/projects/tasks/timer/start_timer/ endpoint (StartTimerView.post).

    Used to start time tracking on a task or project.
    """
    workspace_id: str | int
    task_id: str | int | None = None
    project_id: str | int | None = None
