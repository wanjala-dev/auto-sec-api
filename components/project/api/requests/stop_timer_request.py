"""Input DTO for stopping time tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopTimerRequest:
    """Input DTO for POST /api/projects/tasks/timer/stop_timer/ endpoint (StopTimerView.post).

    Used to stop time tracking on a task or project.
    """
    task_id: str | int | None = None
    project_id: str | int | None = None
