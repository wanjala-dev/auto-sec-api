"""
Helpers for preparing kanban/task payloads for sync.

These functions are intentionally side-effect free; the actual create/update
against the Task/Column models should be performed by the caller after applying
the resolved status/column mapping and ensuring columns exist.
"""
from __future__ import annotations

from typing import Dict, Optional

from components.agents.domain.value_objects.plan_schemas import TaskSpec, TaskStatus, Priority

_DEFAULT_COLUMN_BY_STATUS = {
    TaskStatus.todo: "Backlog",
    TaskStatus.done: "Complete",
    TaskStatus.archived: "Canceled",
}


def status_from_column(title: str) -> TaskStatus:
    """Map a column title back to the closest TaskStatus."""
    normalized = (title or "").strip().lower()
    if normalized in {"complete", "completed", "done", "finished"}:
        return TaskStatus.done
    if normalized in {"cancelled", "canceled", "archive", "archived"}:
        return TaskStatus.archived
    return TaskStatus.todo


def column_title_for_status(status: TaskStatus) -> str:
    """Return a default column title for the given status."""
    return _DEFAULT_COLUMN_BY_STATUS.get(status, "Todo")


_FALLBACK_BOARD_COLUMNS = (
    ("Backlog", 0),
    ("Todo", 1),
    ("In Progress", 2),
    ("Review", 3),
    ("Complete", 4),
)


def normalize_task_for_kanban(
    task: TaskSpec,
    *,
    default_columns: tuple = _FALLBACK_BOARD_COLUMNS,
) -> Dict[str, Optional[str]]:
    """
    Prepare a TaskSpec for kanban syncing by normalizing status/column/priority.

    *default_columns* is a sequence of ``(title, order)`` pairs; the gateway
    layer passes the workspace-specific list.  Defaults to a sensible
    built-in set so the domain function stays side-effect-free.

    Returns a lightweight dict to be consumed by the DB upsert layer.
    """
    column_hint = task.column.title if task.column else None
    status = task.status or TaskStatus.todo
    column_title = column_hint or column_title_for_status(status)

    # Respect the default column ordering; caller can use this as a hint.
    default_order_map = {title.lower(): order for title, order in default_columns}
    column_order_hint = default_order_map.get(column_title.lower())

    priority = task.priority if isinstance(task.priority, Priority) else Priority.medium

    return {
        "title": task.title,
        "status": status.value,
        "column_title": column_title,
        "column_order_hint": column_order_hint,
        "priority": priority.value,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "assignee_id": task.assignee_id,
        "assignee_type": task.assignee_type.value if task.assignee_type else None,
        "project_id": task.project_id,
        "workspace_id": task.workspace_id,
        "team_id": task.team_id,
        "parent_task_id": task.parent_task_id,
        "order": task.order,
        "description": task.description,
        "artifacts": [art.model_dump() for art in task.artifacts],
    }
