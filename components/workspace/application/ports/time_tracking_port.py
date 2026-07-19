"""Port: Time tracking operations for project entries.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TimerStartResult:
    """Result of starting a timer."""

    entry_id: Any
    total_tracked_minutes: int


@dataclass(frozen=True)
class TimerStopResult:
    """Result of stopping a timer."""

    entry_id: Any
    tracked_minutes: int
    total_tracked_minutes: int


@dataclass(frozen=True)
class TimerDiscardResult:
    """Result of discarding a timer."""

    total_tracked_minutes: int


class TimeTrackingPort(abc.ABC):
    """Secondary port for time-tracking persistence operations."""

    @abc.abstractmethod
    def validate_workspace(self, workspace_id: Any) -> Any:
        """Return workspace or raise ValueError if not found."""
        ...

    @abc.abstractmethod
    def resolve_active_team_for_timer(self, *, user: Any) -> Any:
        """Return the user's active team or raise ValueError."""
        ...

    @abc.abstractmethod
    def validate_team_workspace(self, *, team: Any, workspace: Any) -> None:
        """Raise ValueError if team doesn't belong to workspace."""
        ...

    @abc.abstractmethod
    def validate_team_membership(self, *, user: Any, team: Any, workspace: Any) -> None:
        """Raise PermissionError if user is not owner or team member."""
        ...

    @abc.abstractmethod
    def validate_task(self, *, task_id: Any, workspace: Any) -> Any:
        """Return task or raise ValueError. Returns None if task_id is None."""
        ...

    @abc.abstractmethod
    def validate_project(self, *, project_id: Any, workspace: Any) -> Any:
        """Return project or raise ValueError. Returns None if project_id is None."""
        ...

    @abc.abstractmethod
    def create_tracked_entry(
        self,
        *,
        workspace: Any,
        team: Any,
        project: Any | None,
        task: Any | None,
        user: Any,
        now: datetime,
    ) -> Any:
        """Create a new tracked time entry and return it."""
        ...

    @abc.abstractmethod
    def total_tracked_minutes_for_task(self, *, task_id: Any, user: Any) -> int:
        """Sum completed (non-tracked) minutes for a task by user. Returns 0 if task_id is None."""
        ...

    @abc.abstractmethod
    def find_active_entry(
        self,
        *,
        team_id: Any,
        user: Any,
        task_id: Any | None,
        project_id: Any | None,
    ) -> Any | None:
        """Find the most recent active timer entry, or None."""
        ...

    @abc.abstractmethod
    def stop_entry(self, *, entry: Any, tracked_minutes: int) -> None:
        """Mark entry as stopped with the given tracked minutes."""
        ...

    @abc.abstractmethod
    def delete_entry(self, *, entry: Any) -> Any | None:
        """Delete an entry. Returns the task_id if it had one, else None."""
        ...
