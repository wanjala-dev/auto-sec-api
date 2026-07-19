"""Use case: Discard (delete) an active time-tracking timer.

No Django imports — depends only on port.
"""
from __future__ import annotations

from typing import Any

from components.workspace.application.ports.time_tracking_port import (
    TimeTrackingPort,
    TimerDiscardResult,
)


class DiscardTimerUseCase:
    """Discard the most recent active timer without recording time."""

    def __init__(self, port: TimeTrackingPort) -> None:
        self._port = port

    def execute(
        self,
        *,
        user: Any,
        task_id: Any | None = None,
        project_id: Any | None = None,
    ) -> TimerDiscardResult:
        team = self._port.resolve_active_team_for_timer(user=user)

        entry = self._port.find_active_entry(
            team_id=team.id,
            user=user,
            task_id=task_id,
            project_id=project_id,
        )
        if entry is None:
            raise LookupError("No active timer to discard.")

        deleted_task_id = self._port.delete_entry(entry=entry)

        total_minutes = 0
        if deleted_task_id:
            total_minutes = self._port.total_tracked_minutes_for_task(
                task_id=deleted_task_id, user=user,
            )

        return TimerDiscardResult(total_tracked_minutes=total_minutes)
