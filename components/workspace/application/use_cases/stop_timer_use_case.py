"""Use case: Stop a running time-tracking timer.

No Django imports — depends only on port.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from components.workspace.application.ports.time_tracking_port import (
    TimeTrackingPort,
    TimerStopResult,
)


class StopTimerUseCase:
    """Stop the most recent active timer and record tracked time."""

    def __init__(self, port: TimeTrackingPort) -> None:
        self._port = port

    def execute(
        self,
        *,
        user: Any,
        task_id: Any | None = None,
        project_id: Any | None = None,
        now: datetime,
    ) -> TimerStopResult:
        team = self._port.resolve_active_team_for_timer(user=user)

        entry = self._port.find_active_entry(
            team_id=team.id,
            user=user,
            task_id=task_id,
            project_id=project_id,
        )
        if entry is None:
            raise LookupError("No active timer found.")

        tracked_minutes = max(1, int((now - entry.created_at).total_seconds() / 60))
        self._port.stop_entry(entry=entry, tracked_minutes=tracked_minutes)

        total_minutes = 0
        if entry.task_id:
            total_minutes = self._port.total_tracked_minutes_for_task(
                task_id=entry.task_id, user=user,
            )

        return TimerStopResult(
            entry_id=entry.id,
            tracked_minutes=tracked_minutes,
            total_tracked_minutes=total_minutes,
        )
