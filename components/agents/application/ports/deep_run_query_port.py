"""Port: read deep-run progress, events, and aggregate stats for the UI.

Separate from existing execution/engagement queries because deep-run data
lives in ``DeepRun`` + ``DeepRunLog`` and is indexed by ``plan_id`` rather
than by ``agent_id``.  Frontend consumes this for the progress bar, the
sub-agent tree, and the dashboard-level stats panels.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class DeepRunEventView:
    """One row from the event log, serialisable to JSON."""

    id: int
    timestamp: datetime
    event_type: str
    status: str
    agent_type: str
    tool_name: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeepRunSubagentView:
    """One sub-agent (worker task) within a deep run.

    Aggregated from the event log: a worker is identified by the
    ``task_id`` in its ``payload``.  We roll up its state by looking at
    the most recent ``worker_*`` event for that task.
    """

    task_id: str
    agent_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    tool_calls: tuple[dict, ...] = ()


@dataclass(frozen=True)
class DeepRunSnapshotView:
    """Top-level view for ``GET /ai/agents/runs/<plan_id>/``.

    Progress is computed at read time as
    ``len(completed_tasks) / max(plan.tasks, 1) * 100``; it's therefore
    honest about what's stored on the run row rather than being a
    separate counter that could drift.
    """

    plan_id: str
    thread_id: str
    workspace_id: str | None
    user_id: str
    status: str
    progress_percent: int
    goal: str
    agent_type: str
    task_count: int
    completed_task_count: int
    started_at: datetime
    updated_at: datetime
    last_error: str
    subagents: tuple[DeepRunSubagentView, ...] = ()


@dataclass(frozen=True)
class DeepRunStatsView:
    """Workspace-level aggregate — one row per ``GET /ai/agents/runs/stats/``."""

    workspace_id: str | None
    total_runs: int
    runs_by_status: dict
    runs_by_agent_type: dict
    tool_call_counts: dict
    failure_rate: float
    window_started_at: datetime | None


class DeepRunQueryPort(ABC):
    """Contract for reading deep-run observability data."""

    @abstractmethod
    def get_snapshot(self, plan_id: str) -> DeepRunSnapshotView | None:
        """Return the run for *plan_id*, or ``None`` if unknown."""
        ...

    @abstractmethod
    def list_events(
        self,
        plan_id: str,
        *,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[DeepRunEventView]:
        """Return events for *plan_id* in chronological order.

        ``since`` lets callers poll — return only events strictly newer
        than the last timestamp they saw.
        """
        ...

    @abstractmethod
    def get_workspace_stats(
        self, workspace_id: str | None = None, *, since: datetime | None = None
    ) -> DeepRunStatsView:
        """Return aggregate stats.  ``workspace_id=None`` = global stats."""
        ...
