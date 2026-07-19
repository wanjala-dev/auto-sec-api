"""ORM adapter that reads ``DeepRun`` + ``DeepRunLog`` for the deep-run observability API.

Progress is derived from the run's ``state`` JSON:

- ``state["plan"]["tasks"]`` gives the total task count
- ``state["completed_tasks"]`` gives the completed count

Sub-agent views are aggregated from the event log:  the worker-level
events (``worker_started``, ``worker_completed``, ``worker_failed``,
``worker_blocked``) carry a ``task_id`` in their payload, and we roll up
each task by its most recent event.  Tool calls come from the same log,
filtered by ``tool_name`` being non-empty.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from django.db.models import Count

from components.agents.application.ports.deep_run_query_port import (
    DeepRunEventView,
    DeepRunQueryPort,
    DeepRunSnapshotView,
    DeepRunStatsView,
    DeepRunSubagentView,
)


def _task_count(state) -> int:
    if not isinstance(state, dict):
        return 0
    plan = state.get("plan") or {}
    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    return len(tasks) if isinstance(tasks, list) else 0


def _completed_count(state) -> int:
    if not isinstance(state, dict):
        return 0
    completed = state.get("completed_tasks") or []
    return len(completed) if isinstance(completed, list) else 0


def _progress_percent(state) -> int:
    total = _task_count(state)
    if total <= 0:
        return 0
    done = _completed_count(state)
    return min(100, int(round(done / total * 100)))


def _event_view(log_row) -> DeepRunEventView:
    return DeepRunEventView(
        id=log_row.id,
        timestamp=log_row.created_at,
        event_type=log_row.event_type,
        status=log_row.status or "",
        agent_type=log_row.agent_type or "",
        tool_name=log_row.tool_name or "",
        payload=log_row.payload or {},
    )


_WORKER_TERMINAL_STATES = {
    "worker_completed": "completed",
    "worker_failed": "failed",
    "worker_blocked": "blocked",
}


def _subagent_views(logs: Iterable) -> tuple[DeepRunSubagentView, ...]:
    """Roll up worker events into per-task sub-agent views.

    A task is identified by ``payload["task_id"]``.  We track the first
    ``worker_started`` as ``started_at`` and the first terminal event as
    ``completed_at``.  Tool calls are collected from rows with a
    non-empty ``tool_name`` tagged with the same ``task_id`` (or no
    task_id, in which case they fall under the most recent task).
    """
    started_at: dict[str, datetime] = {}
    completed_at: dict[str, datetime] = {}
    status: dict[str, str] = {}
    agent_type: dict[str, str] = {}
    tool_calls: dict[str, list[dict]] = defaultdict(list)

    ordered = sorted(logs, key=lambda row: row.created_at)
    last_task_id: str | None = None

    for row in ordered:
        payload = row.payload or {}
        task_id = str(payload.get("task_id") or "")
        if task_id:
            last_task_id = task_id

        if row.event_type == "worker_started" and task_id:
            started_at.setdefault(task_id, row.created_at)
            status[task_id] = "running"
            if row.agent_type:
                agent_type[task_id] = row.agent_type

        elif row.event_type in _WORKER_TERMINAL_STATES and task_id:
            completed_at.setdefault(task_id, row.created_at)
            status[task_id] = _WORKER_TERMINAL_STATES[row.event_type]
            if row.agent_type and task_id not in agent_type:
                agent_type[task_id] = row.agent_type

        if row.tool_name:
            bucket = task_id or last_task_id or ""
            if bucket:
                tool_calls[bucket].append(
                    {
                        "tool_name": row.tool_name,
                        "agent_type": row.agent_type or "",
                        "status": row.status or "",
                        "timestamp": row.created_at.isoformat(),
                    }
                )

    task_ids = sorted(
        set(started_at) | set(completed_at) | set(status) | set(tool_calls),
        key=lambda tid: started_at.get(tid, datetime.max),
    )
    views: list[DeepRunSubagentView] = []
    for task_id in task_ids:
        views.append(
            DeepRunSubagentView(
                task_id=task_id,
                agent_type=agent_type.get(task_id, ""),
                status=status.get(task_id, "unknown"),
                started_at=started_at.get(task_id),
                completed_at=completed_at.get(task_id),
                tool_calls=tuple(tool_calls.get(task_id, ())),
            )
        )
    return tuple(views)


class OrmDeepRunQueryRepository(DeepRunQueryPort):
    """Reads from ``DeepRun`` + ``DeepRunLog`` ORM models."""

    def get_snapshot(self, plan_id: str) -> DeepRunSnapshotView | None:
        from infrastructure.persistence.ai.agents.models import DeepRun

        run = (
            DeepRun.objects.filter(plan_id=plan_id)
            .select_related("workspace", "user")
            .order_by("-updated_at")
            .first()
        )
        if run is None:
            return None

        logs = list(run.logs.all().order_by("created_at"))
        state = run.state if isinstance(run.state, dict) else {}
        plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
        run_metadata = state.get("run_metadata") if isinstance(state.get("run_metadata"), dict) else {}

        return DeepRunSnapshotView(
            plan_id=run.plan_id,
            thread_id=run.thread_id,
            workspace_id=str(run.workspace_id) if run.workspace_id else None,
            user_id=str(run.user_id),
            status=run.status,
            progress_percent=_progress_percent(state),
            goal=str(plan.get("goal") or run_metadata.get("goal") or ""),
            agent_type=str(run_metadata.get("agent_type") or ""),
            task_count=_task_count(state),
            completed_task_count=_completed_count(state),
            started_at=run.created_at,
            updated_at=run.updated_at,
            last_error=run.last_error or "",
            subagents=_subagent_views(logs),
        )

    def list_events(
        self,
        plan_id: str,
        *,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[DeepRunEventView]:
        from infrastructure.persistence.ai.agents.models import DeepRun

        run = DeepRun.objects.filter(plan_id=plan_id).order_by("-updated_at").first()
        if run is None:
            return []

        queryset = run.logs.all().order_by("created_at")
        if since is not None:
            queryset = queryset.filter(created_at__gt=since)
        return [_event_view(row) for row in queryset[:limit]]

    def get_workspace_stats(
        self, workspace_id: str | None = None, *, since: datetime | None = None
    ) -> DeepRunStatsView:
        from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog

        runs_qs = DeepRun.objects.all()
        logs_qs = DeepRunLog.objects.all()
        if workspace_id is not None:
            runs_qs = runs_qs.filter(workspace_id=workspace_id)
            logs_qs = logs_qs.filter(deep_run__workspace_id=workspace_id)
        if since is not None:
            runs_qs = runs_qs.filter(created_at__gte=since)
            logs_qs = logs_qs.filter(created_at__gte=since)

        total_runs = runs_qs.count()
        runs_by_status = {
            row["status"]: row["n"]
            for row in runs_qs.values("status").annotate(n=Count("id"))
        }
        failed = runs_by_status.get("failed", 0)
        failure_rate = (failed / total_runs) if total_runs else 0.0

        agent_type_counts: dict[str, int] = defaultdict(int)
        for row in runs_qs.values_list("state", flat=True):
            if not isinstance(row, dict):
                continue
            meta = row.get("run_metadata") if isinstance(row.get("run_metadata"), dict) else {}
            slug = str(meta.get("agent_type") or "")
            if slug:
                agent_type_counts[slug] += 1

        tool_call_counts = {
            row["tool_name"]: row["n"]
            for row in (
                logs_qs.exclude(tool_name="")
                .values("tool_name")
                .annotate(n=Count("id"))
                .order_by("-n")[:50]
            )
        }

        window_started_at = since or (
            runs_qs.order_by("created_at").values_list("created_at", flat=True).first()
        )

        return DeepRunStatsView(
            workspace_id=workspace_id,
            total_runs=total_runs,
            runs_by_status=runs_by_status,
            runs_by_agent_type=dict(agent_type_counts),
            tool_call_counts=tool_call_counts,
            failure_rate=round(failure_rate, 4),
            window_started_at=window_started_at,
        )
