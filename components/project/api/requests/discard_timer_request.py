"""Input DTO for discarding untracked time entries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscardTimerRequest:
    """Input DTO for POST /api/projects/tasks/timer/discard_timer/ endpoint (DiscardTimerView.post).

    Used to discard untracked time entries for a task or project.
    """
    task_id: str | int | None = None
    project_id: str | int | None = None
