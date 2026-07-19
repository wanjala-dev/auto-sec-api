"""
Lightweight planner helpers for bootstrapping PlanSpec objects.

These are deliberately minimal: they convert provided actions/task dicts into
TaskSpec instances and wrap them in a PlanSpec. Callers can layer LLM-based
planning on top later.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from components.agents.domain.value_objects.plan_schemas import (
    AssigneeType,
    ColumnSuggestion,
    PlanSpec,
    Priority,
    TaskSpec,
    TaskStatus,
)


def _coerce_priority(value: Any) -> Priority:
    if isinstance(value, Priority):
        return value
    lowered = str(value or "").lower()
    for choice in Priority:
        if lowered == choice.value:
            return choice
    return Priority.medium


def _coerce_status(value: Any) -> TaskStatus:
    if isinstance(value, TaskStatus):
        return value
    lowered = str(value or "").lower()
    for choice in TaskStatus:
        if lowered == choice.value:
            return choice
    return TaskStatus.todo


def _coerce_assignee_type(value: Any) -> AssigneeType:
    if isinstance(value, AssigneeType):
        return value
    lowered = str(value or "").lower()
    for choice in AssigneeType:
        if lowered == choice.value:
            return choice
    return AssigneeType.human


def _parse_due_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(str(value), fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def build_plan_from_actions(
    plan_id: str,
    goal: str,
    actions: Iterable[Dict[str, Any]],
) -> PlanSpec:
    """
    Convert a list of task/action dicts into a PlanSpec without LLM planning.

    Expected keys per action (all optional except title): title, description,
    priority, due_date, project_id, workspace_id, team_id, column_title/column_id,
    status, assignee_id, assignee_type, parent_task_id, order, artifacts.
    """
    tasks: List[TaskSpec] = []
    for action in actions:
        if not action:
            continue
        title = action.get("title") or action.get("summary")
        if not title:
            continue
        column = None
        if action.get("column_id") or action.get("column_title"):
            column = ColumnSuggestion(
                id=action.get("column_id"),
                title=action.get("column_title"),
                status_hint=_coerce_status(action.get("status")),
            )
        task = TaskSpec(
            id=str(action.get("id")) if action.get("id") else None,
            title=str(title),
            description=action.get("description"),
            priority=_coerce_priority(action.get("priority")),
            due_date=_parse_due_date(action.get("due_date")),
            project_id=action.get("project_id"),
            workspace_id=action.get("workspace_id"),
            team_id=action.get("team_id"),
            column=column,
            status=_coerce_status(action.get("status")),
            assignee_id=action.get("assignee_id"),
            assignee_type=_coerce_assignee_type(action.get("assignee_type")),
            parent_task_id=action.get("parent_task_id"),
            order=action.get("order"),
            artifacts=[],
            metadata=action.get("metadata") or {},
            # Per-task specialist agent routing. Planner emits a string
            # like "budget_agent" / "sponsorship_agent" so the runner
            # dispatches each task to the right specialist instead of
            # forcing every task through the chat's default agent.
            # ``None`` means "fall back to the chat's default".
            agent_type=action.get("agent_type") or None,
        )
        tasks.append(task)
    return PlanSpec(plan_id=plan_id, goal=goal, tasks=tasks)

