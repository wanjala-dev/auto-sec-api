"""Use case: Start a time-tracking timer.

No Django imports — depends only on port.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from components.workspace.application.ports.time_tracking_port import (
    TimeTrackingPort,
    TimerStartResult,
)


class StartTimerUseCase:
    """Start a tracked timer for a workspace/project/task."""

    def __init__(self, port: TimeTrackingPort) -> None:
        self._port = port

    def execute(
        self,
        *,
        user: Any,
        workspace_id: Any,
        task_id: Any | None = None,
        project_id: Any | None = None,
        now: datetime,
    ) -> TimerStartResult:
        workspace = self._port.validate_workspace(workspace_id)
        team = self._port.resolve_active_team_for_timer(user=user)
        self._port.validate_team_workspace(team=team, workspace=workspace)
        self._port.validate_team_membership(user=user, team=team, workspace=workspace)

        task = self._port.validate_task(task_id=task_id, workspace=workspace)
        project = task.project if task and hasattr(task, "project") else None
        if not project:
            project = self._port.validate_project(project_id=project_id, workspace=workspace)

        entry = self._port.create_tracked_entry(
            workspace=workspace,
            team=team,
            project=project,
            task=task,
            user=user,
            now=now,
        )

        total_minutes = self._port.total_tracked_minutes_for_task(
            task_id=task.id if task else None, user=user,
        )

        return TimerStartResult(
            entry_id=entry.id,
            total_tracked_minutes=total_minutes,
        )
