"""
Idempotent helpers to sync a TaskSpec into the kanban/task models.

Side effects:
- Ensures default board columns exist for the team/workspace.
- Creates or updates a Column and Task as needed.
- Applies basic status/column/priority/due date/assignee updates.

Notes:
- The Task model currently has no description field; descriptions are ignored for persistence.
- Agent assignees are not persisted (the Task model only tracks human users).
"""
from __future__ import annotations

from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from components.agents.domain.services.deep.kanban_sync import normalize_task_for_kanban, status_from_column
from components.agents.domain.value_objects.plan_schemas import TaskSpec, TaskStatus, Priority, AssigneeType


def _get_project_models():
    from infrastructure.persistence.project.models import Task, Column, Project, TaskComment
    return Task, Column, Project, TaskComment


def _get_workspace_models():
    from infrastructure.persistence.workspaces.models import Workspace
    return Workspace


def _get_team_models():
    from infrastructure.persistence.team.models import Team
    return Team


def _get_user_models():
    from infrastructure.persistence.users.models import CustomUser
    return CustomUser


def _get_agent_models():
    from infrastructure.persistence.ai.agents.models import Agent
    return Agent


def _resolve_priority(priority: str | Priority | None) -> str:
    Task, _, _, _ = _get_project_models()
    if isinstance(priority, Priority):
        return priority.value
    value = (priority or "").lower()
    if value in {choice for choice, _ in Task.Priority.choices}:
        return value
    return Task.Priority.MEDIUM


def _resolve_assignee(task_payload: TaskSpec):
    CustomUser = _get_user_models()
    Agent = _get_agent_models()
    if not task_payload.assignee_id:
        return None
    if task_payload.assignee_type == AssigneeType.agent:
        try:
            agent = Agent.objects.select_related("user").get(agent_id=task_payload.assignee_id)
        except Agent.DoesNotExist:
            return None
        return agent.user
    if task_payload.assignee_type == AssigneeType.human:
        try:
            return CustomUser.objects.get(id=task_payload.assignee_id)
        except CustomUser.DoesNotExist:
            return None
    return None


def _resolve_project(project_id: Optional[str], workspace_id: Optional[str]):
    _, _, Project, _ = _get_project_models()
    if not project_id or not workspace_id:
        return None
    try:
        return Project.objects.get(id=project_id, workspace_id=workspace_id)
    except Project.DoesNotExist:
        return None


def _resolve_team_and_workspace(team_id: Optional[str], workspace_id: Optional[str]) -> Tuple[Optional, Optional]:
    Team = _get_team_models()
    Workspace = _get_workspace_models()
    team = None
    workspace = None
    if workspace_id:
        workspace = Workspace.objects.filter(id=workspace_id).first()
    if team_id:
        team = Team.objects.filter(id=team_id).select_related("workspace").first()
        if team and not workspace:
            workspace = team.workspace
    return team, workspace


def _resolve_column(team, workspace, title: str, *, order_hint: Optional[int], owner):
    _, Column, _, _ = _get_project_models()
    existing = Column.objects.filter(team=team, workspace=workspace, title__iexact=title).first()
    if existing:
        updates = []
        if order_hint is not None and existing.order != order_hint:
            existing.order = order_hint
            updates.append("order")
        if existing.project_id is not None:
            existing.project = None
            updates.append("project")
        if owner and existing.created_by_id is None:
            existing.created_by = owner
            updates.append("created_by")
        if updates:
            existing.save(update_fields=updates)
        return existing
    return Column.objects.create(
        team=team,
        workspace=workspace,
        title=title,
        order=order_hint or 0,
        project=None,
        created_by=owner,
    )


def _ensure_description_comment(task, description: Optional[str], author) -> None:
    """
    Persist a description on the Task via a TaskComment if provided.

    The Task model lacks a description field; we attach the text as the first comment
    to preserve context without duplicating comments on subsequent syncs.
    """
    _, _, _, TaskComment = _get_project_models()
    if not description:
        return
    if TaskComment.objects.filter(task=task, comment=description).exists():
        return
    TaskComment.objects.create(
        task=task,
        comment=description,
        author=author or task.created_by,
    )


def upsert_task_from_spec(task_spec: TaskSpec, *, created_by_id: Optional[str] = None):
    """
    Create or update a Task and its Column based on a TaskSpec.

    Returns the Task instance on success, or None if required context (team/workspace) is missing.

    Notes:
    - Agent assignees are ignored (Task model only supports human users). TODO: extend model if agent assignment is required.
    - Task descriptions are not persisted (model lacks description field today). TODO: add description field if needed.
    """
    Task, _, _, _ = _get_project_models()
    CustomUser = _get_user_models()

    team, workspace = _resolve_team_and_workspace(task_spec.team_id, task_spec.workspace_id)
    if not team or not workspace:
        return None

    owner = None
    if created_by_id:
        owner = CustomUser.objects.filter(id=created_by_id).first()
    if not owner:
        owner = getattr(workspace, "workspace_owner", None)

    # Ensure default columns exist to avoid duplication later.
    try:
        from infrastructure.persistence.workspaces.utils import ensure_team_board_columns
        ensure_team_board_columns(workspace, team, owner)
    except Exception:
        # Non-fatal; continue with best-effort column resolution.
        pass

    normalized = normalize_task_for_kanban(task_spec)
    column_title = normalized["column_title"]
    column_order_hint = normalized["column_order_hint"]
    status = task_spec.status or status_from_column(column_title)

    with transaction.atomic():
        column = _resolve_column(team, workspace, column_title, order_hint=column_order_hint, owner=owner)
        project = _resolve_project(task_spec.project_id, task_spec.workspace_id)

        task = None
        task_id = None
        if task_spec.id:
            try:
                task_id = int(task_spec.id)
            except (TypeError, ValueError):
                task_id = None
        if task_id:
            task = Task.objects.filter(id=task_id).select_related("team", "workspace").first()
            if task and (task.team_id != team.id or task.workspace_id != workspace.id):
                # Task belongs to a different context; do not mutate.
                task = None

        if not task:
            # Create
            task = Task.objects.create(
                workspace=workspace,
                team=team,
                project=project,
                column=column,
                title=normalized["title"],
                created_by=owner or CustomUser.objects.filter(is_staff=True).first(),
                status=status.value if isinstance(status, TaskStatus) else str(status),
                order=normalized["order"] or 0,
                priority=_resolve_priority(normalized["priority"]),
            )
        else:
            # Update selected fields
            fields = []
            if task.title != normalized["title"]:
                task.title = normalized["title"]
                fields.append("title")
            if task.column_id != column.id:
                task.column = column
                fields.append("column")
            target_status = status.value if isinstance(status, TaskStatus) else str(status)
            if task.status != target_status:
                task.status = target_status
                fields.append("status")
            prio = _resolve_priority(normalized["priority"])
            if task.priority != prio:
                task.priority = prio
                fields.append("priority")
            if normalized["order"] is not None and task.order != normalized["order"]:
                task.order = normalized["order"]
                fields.append("order")
            if project and task.project_id != project.id:
                task.project = project
                fields.append("project")
            if normalized["due_date"]:
                try:
                    # due_date from normalize is ISO string
                    parsed = timezone.datetime.fromisoformat(normalized["due_date"])
                    if task.due_date != parsed:
                        task.due_date = parsed
                        fields.append("due_date")
                except Exception:
                    pass
            if fields:
                task.save(update_fields=fields)

        assignee = _resolve_assignee(task_spec)
        if assignee:
            task.assigned_to.add(assignee)

        _ensure_description_comment(task, normalized.get("description"), owner)

        return task
