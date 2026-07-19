"""Reusable task management agent tools."""
from __future__ import annotations

import json
import uuid
import re
from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional

from django.db.models import Q
from django.utils import timezone


def _coerce_payload(payload: Any) -> Dict[str, Any]:
    """Coerce tool input into a dict. Accepts dict or JSON string."""
    if payload in (None, "", {}):
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            # not JSON; return empty to trigger validation error below
            return {}
    return {}


def _resolve_user(agent, identifier: Any = None):
    from infrastructure.persistence.users.models import CustomUser

    candidates = []

    def _append(value: Any):
        if value in (None, "", {}):
            return
        if isinstance(value, str):
            normalized = value.strip().strip("'\"“”‘’")
            if not normalized:
                return
            candidates.append(normalized)
        else:
            candidates.append(str(value).strip())

    if isinstance(identifier, dict):
        for key in ("user_id", "id", "email", "username", "name", "text"):
            _append(identifier.get(key))
    else:
        _append(identifier)

    config = getattr(agent, 'config', {}) or {}
    for key in ("default_user_id", "default_user_email", "default_username", "default_user_name"):
        _append(config.get(key))

    _append(getattr(agent, 'user_id', None))
    try:
        teammate_profile = agent.action_service.get_teammate(agent.workspace_id) if hasattr(agent, "action_service") else None
        ai_user = getattr(teammate_profile, "user", None)
        _append(ai_user.id if ai_user else None)
        _append(ai_user.email if ai_user else None)
    except Exception:
        pass

    seen = set()
    for candidate in candidates:
        token = candidate.lower()
        if token in {"me", "myself", "self", "owner", "current user"}:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            uuid.UUID(candidate)
            return CustomUser.objects.get(id=candidate)
        except Exception:
            pass
        try:
            return CustomUser.objects.get(email__iexact=candidate)
        except CustomUser.DoesNotExist:
            pass
        try:
            return CustomUser.objects.get(username__iexact=candidate)
        except CustomUser.DoesNotExist:
            pass
        try:
            return CustomUser.objects.get(
                Q(first_name__icontains=candidate) | Q(last_name__icontains=candidate)
            )
        except CustomUser.MultipleObjectsReturned:
            continue
        except CustomUser.DoesNotExist:
            continue

    return None


def _extract_task_title_from_prompt(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"assigned to (?:the )?(?P<title>.+?)(?: task)?[?!.]*$",
        r"assignment for (?:the )?(?P<title>.+?)(?: task)?[?!.]*$",
        r"who is on (?:the )?(?P<title>.+?)(?: task)?[?!.]*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            title = match.group("title").strip()
            title = re.sub(r"\btask\b", "", title, flags=re.IGNORECASE).strip()
            return title.strip("'\"“”‘’")
    return ""

def parse_task_request(agent, text: str) -> str:
    try:
        title = text.strip()

        assignee = None
        for pattern in [r'assign to (\w+)', r'give to (\w+)', r'(\w+) should do', r'for (\w+)']:
            match = re.search(pattern, text.lower())
            if match:
                assignee = match.group(1)
                break

        due_date = None
        for pattern in [
            r'due (\d{4}-\d{2}-\d{2})',
            r'by (\d{1,2}/\d{1,2}/\d{4})',
            r'deadline (\d{1,2}-\d{1,2}-\d{4})',
            r'tomorrow',
            r'next week',
            r'this friday',
        ]:
            match = re.search(pattern, text.lower())
            if not match:
                continue
            token = match.group(0)
            if token == 'tomorrow':
                due_date = (date.today() + timedelta(days=1)).isoformat()
            elif token == 'next week':
                due_date = (date.today() + timedelta(days=7)).isoformat()
            elif token == 'this friday':
                days_until_friday = (4 - date.today().weekday()) % 7
                due_date = (date.today() + timedelta(days=days_until_friday)).isoformat()
            else:
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y'):
                    try:
                        due_date = datetime.strptime(match.group(1), fmt).date().isoformat()
                        break
                    except (ValueError, IndexError):
                        continue
            if due_date:
                break

        priority = 'medium'
        lowered = text.lower()
        if any(word in lowered for word in ['urgent', 'asap', 'high priority']):
            priority = 'high'
        elif any(word in lowered for word in ['low priority', 'when possible']):
            priority = 'low'

        project = None
        for pattern in [r'in project (\w+)', r'for project (\w+)', r'under (\w+) project']:
            match = re.search(pattern, lowered)
            if match:
                project = match.group(1)
                break

        result = {
            'title': title,
            'assignee': assignee,
            'due_date': due_date,
            'priority': priority,
            'project': project,
            'raw_text': text,
        }
        return f"Parsed task request: {result}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error parsing task request: {exc}"


def create_task(agent, params: Any) -> str:
    """Create a new task. Accepts either a JSON dict (preferred — supports
    description/assignee/project/due_date/column_title) or a plain string
    that becomes the title.
    """
    try:
        # Allow the legacy dict shape AND a bare title string. The
        # smoke harness passes "{}" — empty dict here means "title is
        # required" (graceful), not a Python KeyError.
        if isinstance(params, str):
            stripped = params.strip()
            if stripped.startswith('{'):
                data = _coerce_payload(stripped)
            else:
                # Plain text string: treat the whole thing as the title.
                data = {'title': stripped} if stripped else {}
        else:
            data = _coerce_payload(params)

        title = (data.get('title') or '').strip()
        if not title:
            return "title is required to create a task."

        description = data.get('description')
        assignee = data.get('assignee')
        project = data.get('project')
        due_date = data.get('due_date')
        column_title = data.get('column_title')

        from infrastructure.persistence.project.models import Project, Task, Column, TaskComment
        from infrastructure.persistence.workspaces.models import Workspace
        # ``ensure_default_columns`` moved to the agents infrastructure
        # tasks module during the DDD/Hex refactor; the legacy
        # ``services.task_service`` path was deleted but this import was
        # left pointing at the dead module, blocking every ``create_task``
        # call (and breaking the social_media agent downstream).
        from components.agents.infrastructure.tasks.service_tasks import ensure_default_columns

        if not check_permissions(agent):
            return "Permission denied: User not authorized to create tasks"

        team = _get_default_team(agent)
        if not team:
            return "No team found for this workspace. Please create a team first."

        project_obj = None
        if project:
            try:
                project_obj = Project.objects.get(workspace_id=agent.workspace_id, title__icontains=project)
            except Project.DoesNotExist:
                return f"Project '{project}' not found. Use get_projects to see available projects."

        creator = _resolve_user(agent)
        if not creator:
            return "Unable to resolve the current user. Please include your user ID or email in the request."

        task = Task.objects.create(
            workspace_id=agent.workspace_id,
            team=team,
            project=project_obj,
            title=title,
            created_by=creator,
            status=Task.TODO,
        )

        if column_title:
            normalized_title = str(column_title).strip()
            column = None
            if project_obj:
                cols = ensure_default_columns(project_obj)
                column = (
                    cols.get(normalized_title)
                    or cols.get(normalized_title.title())
                    or next(
                        (col for name, col in cols.items() if name.lower() == normalized_title.lower()),
                        None,
                    )
                )
            if not column:
                # Fall back to any existing column with that title in
                # the team's workspace. The team-board-bootstrap helper
                # was removed; project-scoped columns above are the
                # canonical source now.
                workspace = Workspace.objects.filter(id=agent.workspace_id).first()
                if workspace:
                    column = Column.objects.filter(
                        workspace=workspace,
                        team=team,
                        project__isnull=True,
                        title__iexact=normalized_title,
                    ).first()
            if column:
                task.column = column
                task.save(update_fields=['column'])

        if assignee:
            assign_result = assign_task(agent, {'task_id': str(task.id), 'assignee': assignee})
            if assign_result.lower().startswith('error'):
                return f"Task created but assignment failed: {assign_result}"

        if due_date:
            try:
                task.due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
                task.save(update_fields=['due_date'])
            except ValueError:
                pass

        if description:
            TaskComment.objects.create(
                task=task,
                author=creator,
                comment=description,
            )

        return f"Successfully created task: '{title}' (ID: {task.id})"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error creating task: {exc}"


def break_down_task(agent, task_id: str, subtasks: str) -> str:
    from infrastructure.persistence.project.models import Task

    try:
        try:
            main_task = Task.objects.get(id=task_id, workspace_id=agent.workspace_id)
        except Task.DoesNotExist:
            return f"Task {task_id} not found"

        subtask_list = [s.strip() for s in subtasks.replace('\n', ',').split(',') if s.strip()]
        if not subtask_list:
            return "No subtasks provided"

        team = main_task.team
        created_subtasks = []
        for index, subtask_title in enumerate(subtask_list):
            subtask = Task.objects.create(
                workspace_id=agent.workspace_id,
                team=team,
                project=main_task.project,
                title=f"{main_task.title} - {subtask_title}",
                created_by=main_task.created_by,
                status=Task.TODO,
                order=index,
            )
            created_subtasks.append(subtask.id)
        return f"Successfully created {len(created_subtasks)} subtasks for task {task_id}: {created_subtasks}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error breaking down task: {exc}"


def assign_task(agent, payload: Any) -> str:
    from infrastructure.persistence.project.models import Task

    try:
        data = _coerce_payload(payload)
        task_id = str(data.get('task_id') or '').strip()
        title_hint = str(data.get('title') or '').strip()
        assignee = str(data.get('assignee') or '').strip()
        if not assignee:
            return "Missing required field: assignee"

        # Resolve task
        task = None
        if task_id:
            try:
                task = Task.objects.get(id=task_id, workspace_id=agent.workspace_id)
            except Task.DoesNotExist:
                return f"Task {task_id} not found"
        elif title_hint:
            task = Task.objects.filter(workspace_id=agent.workspace_id, title__icontains=title_hint).order_by('-created_at').first()
            if not task:
                return f"Task with title like '{title_hint}' not found"
        else:
            # Fallback to most recently created task in this workspace (likely the one just created)
            task = Task.objects.filter(workspace_id=agent.workspace_id).order_by('-created_at').first()
            if not task:
                return "No tasks found to assign. Please specify task_id or title."

        # Resolve assignee
        if assignee.lower() in {"me", "myself", "self", "owner"}:
            user = _resolve_user(agent)
        else:
            user = _resolve_user(agent, assignee)
        if not user:
            return f"User '{assignee}' could not be resolved. Provide an email, username, or user ID."

        if not task.team.members.filter(id=user.id).exists():
            return f"User '{assignee}' is not a member of the team"

        task.assigned_to.add(user)
        return f"Successfully assigned task '{task.title}' to {user.get_full_name() or user.username}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error assigning task: {exc}"


def get_task_assignment(agent, payload: Any = None, task_id: str | None = None, title: str | None = None) -> str:
    """Return the current assignees for a task by id or partial title."""
    from infrastructure.persistence.project.models import Task

    try:
        if not getattr(agent, 'workspace_id', None):
            return "No workspace context is set for this agent. Please bind the agent to a workspace."

        data = _coerce_payload(payload)

        # Allow simple string inputs (e.g., task title) without JSON encoding
        if isinstance(payload, str) and not data:
            raw = payload.strip()
            if raw:
                extracted = _extract_task_title_from_prompt(raw)
                if extracted:
                    title = title or extracted
                    raw = extracted
                if raw.replace('-', '').isdigit():
                    task_id = task_id or raw
                else:
                    title = title or raw

        task_id = task_id or data.get('task_id') or data.get('id')
        title = title or data.get('title') or data.get('name') or data.get('task') or data.get('text')

        task = None
        if task_id:
            try:
                task = Task.objects.get(id=task_id, workspace_id=agent.workspace_id)
            except Task.DoesNotExist:
                return f"Task {task_id} not found"
        elif title:
            task = (
                Task.objects.filter(workspace_id=agent.workspace_id, title__icontains=title)
                .order_by('-created_at')
                .first()
            )
            if not task:
                return f"Task with title like '{title}' not found"
        else:
            return "Provide a task_id or title to look up the assignment."

        assignees = list(
            task.assigned_to.all().values('id', 'email', 'username', 'first_name', 'last_name')
        )
        if not assignees:
            return f"Task '{task.title}' (ID: {task.id}) has no assignees."

        for entry in assignees:
            name = f"{entry.get('first_name', '')} {entry.get('last_name', '')}".strip()
            entry['name'] = name or entry.get('username') or entry.get('email')

        return (
            f"Task '{task.title}' (ID: {task.id}) assignees: "
            f"{assignees}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error getting task assignment: {exc}"


def get_team_members(agent, _input: Any | None = None) -> str:
    from infrastructure.persistence.team.models import Team

    try:
        teams = Team.objects.filter(workspace_id=agent.workspace_id, status='active').exclude(kind=Team.Kind.AI_AGENTS)
        if not teams.exists():
            return "No active teams found for this workspace"

        members = []
        for team in teams:
            for member in team.members.all():
                members.append(
                    {
                        'id': member.id,
                        'name': member.get_full_name() or member.username,
                        'email': member.email,
                        'team': team.title,
                    }
                )
        if not members:
            return "No team members found"
        return f"Available team members: {members}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error getting team members: {exc}"


def get_members_without_tasks(agent, payload: Any = None) -> str:
    """Return team members who currently have no tasks assigned."""
    from infrastructure.persistence.project.models import Task
    from infrastructure.persistence.team.models import Team

    try:
        if not getattr(agent, 'workspace_id', None):
            return "No workspace context is set for this agent. Please bind the agent to a workspace."

        data = _coerce_payload(payload)
        team_id = data.get('team_id') or data.get('team')

        teams = Team.objects.filter(workspace_id=agent.workspace_id, status='active').exclude(kind=Team.Kind.AI_AGENTS)
        if team_id:
            teams = teams.filter(id=team_id)

        if not teams.exists():
            return "No active teams found for this workspace"

        members = []
        for team in teams.prefetch_related('members'):
            members.extend(list(team.members.all()))

        if not members:
            return "No team members found"

        member_ids = [m.id for m in members]
        member_lookup = {m.id: m for m in members}

        assigned_ids = set(
            Task.objects.filter(workspace_id=agent.workspace_id, assigned_to__in=member_ids)
            .values_list('assigned_to', flat=True)
            .distinct()
        )

        unassigned = [
            {
                'id': str(user.id),
                'name': user.get_full_name() or user.username,
                'email': user.email,
            }
            for user in members
            if user.id not in assigned_ids
        ]

        if not unassigned:
            return "All team members currently have at least one task assigned."

        return f"{len(unassigned)} team members have no tasks: {unassigned}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error getting members without tasks: {exc}"


def get_projects(agent, _input: Any | None = None) -> str:
    from infrastructure.persistence.project.models import Project

    try:
        projects = Project.objects.filter(workspace_id=agent.workspace_id).values('id', 'title', 'description')
        if not projects.exists():
            return "No projects found for this workspace"
        return f"Available projects: {list(projects)}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error getting projects: {exc}"


def get_user_tasks(agent, user_id: Any = None) -> str:
    from infrastructure.persistence.project.models import Task

    try:
        # Ensure we have a workspace context
        if not getattr(agent, 'workspace_id', None):
            return "No workspace context is set for this agent. Please bind the agent to a workspace."

        explicit = None
        if isinstance(user_id, str):
            explicit = user_id.strip()
            if explicit and any(token in explicit.lower() for token in ("task", "project")):
                return (
                    "This tool lists tasks for a user. To see who is assigned to a task, "
                    "call get_task_assignment with a task_id or task title. "
                    "To find members without tasks, call get_members_without_tasks."
                )

        user = _resolve_user(agent, user_id)
        if not user:
            identifier = user_id or getattr(agent, 'user_id', None)
            if identifier:
                token = str(identifier)
                # Help steer the agent away from task-lookup misuse
                if "task" in token.lower() or "project" in token.lower():
                    return (
                        "This tool lists tasks for a user. To see who is assigned to a task, "
                        "call get_task_assignment with a task_id or task title. "
                        "To find members without tasks, call get_members_without_tasks."
                    )
                return f"User '{identifier}' not found. Please provide an explicit email, username, or user ID."
            return "Unable to resolve a user for this request. Include an email, username, or ID in your prompt."

        tasks = Task.objects.filter(workspace_id=agent.workspace_id, assigned_to=user).values('id', 'title', 'status', 'created_at')
        if not tasks.exists():
            return f"No tasks assigned to {user.get_full_name() or user.username}"
        return f"Tasks assigned to {user.get_full_name() or user.username}: {list(tasks)}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error getting user tasks: {exc}"


def get_due_tasks(agent, payload: Any = None) -> str:
    from infrastructure.persistence.project.models import Task

    try:
        if not getattr(agent, 'workspace_id', None):
            return "No workspace context is set for this agent. Please bind the agent to a workspace."

        data = _coerce_payload(payload)
        user_hint = (
            data.get('user')
            or data.get('user_id')
            or data.get('assignee')
            or data.get('owner')
            or data.get('id')
        )
        user = _resolve_user(agent, user_hint) or _resolve_user(agent)
        if not user:
            return "Unable to resolve a user for this request. Provide an explicit email, username, or user ID."

        token = data.get('date') or data.get('target_date') or data.get('due_date')
        target_date = timezone.localdate()
        if isinstance(token, str):
            normalized = token.strip().lower()
            if normalized in {'', 'today', 'current', 'now'}:
                target_date = timezone.localdate()
            elif normalized == 'tomorrow':
                target_date = timezone.localdate() + timedelta(days=1)
            else:
                parsed = None
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y'):
                    try:
                        parsed = datetime.strptime(token.strip(), fmt).date()
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    return f"Unable to parse date value '{token}'. Use YYYY-MM-DD or specify 'today'/'tomorrow'."
                target_date = parsed
        elif isinstance(token, (date, datetime)):
            target_date = token if isinstance(token, date) else token.date()

        due_tasks = (
            Task.objects.filter(
                workspace_id=agent.workspace_id,
                assigned_to=user,
                due_date__isnull=False,
                due_date__date=target_date,
            )
            .exclude(status__in=[Task.DONE, Task.ARCHIVED])
            .select_related('project')
            .order_by('due_date', 'title')
        )

        if not due_tasks.exists():
            label = user.get_full_name() or user.username or str(user.id)
            return f"No outstanding tasks due on {target_date.isoformat()} for {label}."

        formatted = [
            {
                'id': str(task.id),
                'title': task.title,
                'status': task.status,
                'due_date': task.due_date.isoformat() if task.due_date else None,
                'priority': task.priority,
                'project': task.project.title if task.project else None,
            }
            for task in due_tasks
        ]
        label = user.get_full_name() or user.username or str(user.id)
        return f"Tasks due on {target_date.isoformat()} for {label}: {formatted}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error getting due tasks: {exc}"


def update_task_status(agent, params: Any) -> str:
    """Update a task's status (todo / done / archived).

    Accepts a JSON dict with ``task_id`` + ``status`` keys. The agent
    wrapper passes a single string arg, so we parse internally rather
    than relying on positional kwargs from the LLM tool-calling path.
    """
    from django.core.exceptions import ValidationError
    from infrastructure.persistence.project.models import Task

    try:
        data = _coerce_payload(params)
        task_id = (str(data.get("task_id") or "").strip())
        status = (str(data.get("status") or "").strip())
        if not task_id:
            return "task_id is required."
        if not status:
            return "status is required ('todo', 'done', or 'archived')."

        try:
            task = Task.objects.get(id=task_id, workspace_id=agent.workspace_id)
        except (Task.DoesNotExist, ValidationError, ValueError):
            return f"Task {task_id} not found in this workspace."

        valid_statuses = [Task.TODO, Task.DONE, Task.ARCHIVED]
        if status.lower() not in [state.lower() for state in valid_statuses]:
            return f"Invalid status: {status}. Valid statuses: {valid_statuses}"

        task.status = status.lower()
        task.save(update_fields=['status'])
        return f"Successfully updated task '{task.title}' status to {status}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error updating task status: {exc}"


def get_task_progress(agent, params: Any = None) -> str:
    """Aggregate progress (counts + completion %) across workspace tasks.

    Accepts a JSON dict with optional ``project_id`` to scope to one
    project. Empty input returns workspace-wide progress.
    """
    from infrastructure.persistence.project.models import Task

    try:
        data = _coerce_payload(params)
        project_id = data.get("project_id") if isinstance(data, dict) else None
        if project_id is not None:
            project_id = str(project_id).strip()
            if project_id.lower() in {"", "none", "null"}:
                project_id = None
            else:
                try:
                    uuid.UUID(project_id)
                except (TypeError, ValueError):
                    return f"Invalid project_id {project_id!r} (must be a UUID)."

        query = Q(workspace_id=agent.workspace_id)
        if project_id:
            query &= Q(project_id=project_id)
        tasks = Task.objects.filter(query)

        total_tasks = tasks.count()
        todo_tasks = tasks.filter(status=Task.TODO).count()
        done_tasks = tasks.filter(status=Task.DONE).count()
        archived_tasks = tasks.filter(status=Task.ARCHIVED).count()
        progress_percentage = (done_tasks / total_tasks * 100) if total_tasks else 0

        progress = {
            'total_tasks': total_tasks,
            'todo_tasks': todo_tasks,
            'done_tasks': done_tasks,
            'archived_tasks': archived_tasks,
            'progress_percentage': round(progress_percentage, 2),
        }
        return f"Task progress: {progress}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error getting task progress: {exc}"


def check_permissions(agent, _input: Any | None = None) -> bool:
    """Return True when the agent user can create tasks for the workspace.

    Access is granted to workspace owners, active team members, and workspace followers
    to support transparent collaboration workflows.
    """
    from infrastructure.persistence.workspaces.models import Workspace
    from infrastructure.persistence.team.models import Team
    from components.agents.application.facades.agent_permissions_facade import ai_can
    from infrastructure.persistence.ai.models import AIPermissionGrant

    try:
        user = _resolve_user(agent)
        if not user:
            return False
        workspace = Workspace.objects.get(id=agent.workspace_id)
        if str(workspace.workspace_owner_id) == str(user.id):
            return True
        if workspace.followers.filter(id=user.id).exists():
            return True
        teams = Team.objects.filter(workspace=workspace, status='active', members=user).exclude(kind=Team.Kind.AI_AGENTS)
        if teams.exists():
            return True
        scope_id = str(teams.first().id) if teams.exists() else None
        return ai_can(
            str(workspace.id),
            str(user.id),
            action="task:write",
            scope_type=AIPermissionGrant.SCOPE_DEPARTMENT,
            scope_id=scope_id,
        )
    except Exception:  # pylint: disable=broad-except
        return False


def _get_default_team(agent) -> Optional['Team']:
    from infrastructure.persistence.team.models import Team
    from infrastructure.persistence.subscription.models import Plan

    try:
        team = (
            Team.objects.filter(workspace_id=agent.workspace_id, status='active')
            .exclude(kind=Team.Kind.AI_AGENTS)
            .first()
        )
        if team:
            return team

        # If no team exists, create a lightweight default team so the agent can proceed.
        creator = _resolve_user(agent)
        if not creator:
            return None
        plan = Plan.objects.filter(is_default=True).first() or Plan.objects.first()
        if plan is None:
            plan = Plan.objects.create(
                title="Starter",
                limits={"max_projects_per_team": 1, "max_members_per_team": 10, "max_tasks_per_project": 50},
                price=0,
                is_default=True,
            )
        # Last-resort home team when the workspace has none (guarded above by
        # "no team exists"). Name it "General" + mark default so it matches the
        # bootstrap convention rather than reintroducing a "Default Team".
        return Team.objects.create(
            workspace_id=agent.workspace_id,
            title="General",
            created_by=creator,
            plan=plan,
            kind=Team.Kind.DEPARTMENT,
            is_default=True,
        )
    except Exception:  # pylint: disable=broad-except
        return None


def list_workspace_tasks(agent, params: Any) -> str:
    """List tasks for the current workspace with optional filters.

    The 2026-05-08 audit found this was the load-bearing missing tool:
    "how many tasks do we have?" had no matching list path, so ReAct
    thrashed and the synthesizer hallucinated 4 fake tasks. This is
    the proven fix shape — mirrors ``project_agent.list_projects``.
    """
    from infrastructure.persistence.project.models import Task

    try:
        data = _coerce_payload(params)

        if not getattr(agent, "workspace_id", None):
            return (
                "No workspace context available for this agent. "
                "Please assign the agent to a workspace before listing tasks."
            )

        # Eager-load FKs the formatter touches so a single page doesn't
        # fan out into N queries (.claude/rules/performance.md §1).
        qs = Task.objects.filter(workspace_id=agent.workspace_id).select_related(
            "project", "column", "created_by"
        ).prefetch_related("assigned_to")

        # Allow ``status`` to be a single value or a list. Default
        # filters out ARCHIVED so chat queries about "tasks" don't
        # surface deleted-by-archive rows.
        status_filter = data.get("status")
        if status_filter:
            if isinstance(status_filter, str):
                qs = qs.filter(status=status_filter)
            elif isinstance(status_filter, (list, tuple, set)):
                qs = qs.filter(status__in=list(status_filter))
        else:
            qs = qs.exclude(status=Task.ARCHIVED)

        project_id = data.get("project_id")
        if project_id:
            try:
                qs = qs.filter(project_id=str(uuid.UUID(str(project_id))))
            except (ValueError, AttributeError, TypeError):
                pass  # invalid UUID → silently ignore the filter

        priority = data.get("priority")
        if priority:
            qs = qs.filter(priority=priority)

        qs = qs.order_by("-created_at")

        limit = data.get("limit")
        if isinstance(limit, int) and limit > 0:
            qs_limited = qs[:limit]
        else:
            qs_limited = qs[:50]  # Hard cap to keep prompts manageable.

        # Materialise once so .count() doesn't run a second query.
        rows = list(qs_limited)
        # ``.count()`` here would re-run the filter without limit;
        # instead surface "showing N (of more)" semantics from the
        # full filtered queryset.
        total_matching = qs.count()

        if total_matching == 0:
            return "No tasks found in this workspace."

        header = (
            f"Tasks ({total_matching} total"
            f"{', showing first ' + str(len(rows)) if len(rows) < total_matching else ''}):\n\n"
        )
        lines = [header]
        for task in rows:
            assigned = (
                ", ".join(
                    (u.get_full_name() or u.email or str(u.id)) for u in task.assigned_to.all()
                )
                or "Unassigned"
            )
            project_label = task.project.title if task.project else "—"
            due = task.due_date.strftime("%Y-%m-%d") if task.due_date else "no due date"
            lines.append(
                "• {title}\n  Status: {status}  Priority: {priority}  Due: {due}\n  "
                "Project: {project}  Assigned: {assigned}\n\n".format(
                    title=task.title,
                    status=task.status,
                    priority=task.priority,
                    due=due,
                    project=project_label,
                    assigned=assigned,
                )
            )
        return "".join(lines)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error listing tasks: {exc}"


# ── Task edits + comments (PR-B2) ──────────────────────────────────────


def _resolve_task_for_update(agent, task_id: Any) -> "tuple[Any, str]":
    """Look up a Task scoped to the agent's workspace.

    Returns ``(task, error)`` — exactly one is set. Centralises the
    "not found / wrong workspace" error path so every update tool emits
    the same shape of error message rather than a stack trace.
    """
    from django.core.exceptions import ValidationError
    from infrastructure.persistence.project.models import Task

    # ``task_id`` arrives as a string (already extracted from the
    # outer JSON payload). Empty / nullish values fall through to the
    # required-field error; valid UUIDs go to the DB lookup.
    cleaned = (str(task_id) if task_id is not None else "").strip()
    if not cleaned or cleaned.lower() in {"none", "null", "undefined"}:
        return None, "task_id is required."

    try:
        task = Task.objects.select_related("project").get(
            id=cleaned, workspace_id=agent.workspace_id
        )
        return task, ""
    except (Task.DoesNotExist, ValidationError, ValueError):
        return None, f"Task {cleaned} not found in this workspace."


def update_task_due_date(agent, params: Any) -> str:
    """Update a task's due_date. Accepts ISO 8601 datetime or date string.

    Pass ``due_date=None`` to clear the due date.
    """
    from datetime import datetime

    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")
        task, err = _resolve_task_for_update(agent, task_id)
        if err:
            return err

        # ``due_date`` of None / "" / "null" clears the field.
        raw = data.get("due_date")
        if raw in (None, "") or (isinstance(raw, str) and raw.strip().lower() in {"none", "null"}):
            task.due_date = None
        else:
            text = str(raw).strip()
            parsed: datetime | None = None
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return (
                    f"Could not parse due_date {text!r}. Use ISO 8601 "
                    "(e.g. '2026-06-15' or '2026-06-15T14:30:00')."
                )
            # Make timezone-aware to match the model's DateTimeField.
            from django.utils import timezone

            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            task.due_date = parsed

        task.save(update_fields=["due_date", "updated_at"])
        when = task.due_date.strftime("%Y-%m-%d %H:%M") if task.due_date else "no due date"
        return f"Updated task '{task.title}' due date to {when}."
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error updating task due date: {exc}"


def update_task_title(agent, params: Any) -> str:
    """Rename a task. Title must be 1-255 characters."""
    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")
        new_title = (data.get("title") or "").strip()

        task, err = _resolve_task_for_update(agent, task_id)
        if err:
            return err

        if not new_title:
            return "title is required."
        if len(new_title) > 255:
            return f"Title too long ({len(new_title)} chars, max 255)."

        old_title = task.title
        task.title = new_title
        task.save(update_fields=["title", "updated_at"])
        return f"Renamed task: {old_title!r} → {new_title!r}."
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error renaming task: {exc}"


def delete_task(agent, params: Any) -> str:
    """Soft-delete a task by setting status=archived.

    The Task model has no ``is_deleted`` field, so archive is the
    canonical "deleted" state — preserves history and keeps comments,
    timer entries, and assignments intact for audit.
    """
    from infrastructure.persistence.project.models import Task

    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")

        task, err = _resolve_task_for_update(agent, task_id)
        if err:
            return err

        if task.status == Task.ARCHIVED:
            return f"Task '{task.title}' is already archived."

        task.status = Task.ARCHIVED
        task.save(update_fields=["status", "updated_at"])
        return (
            f"Archived task '{task.title}'. Status set to '{Task.ARCHIVED}'. "
            "(The Task model has no hard-delete; archive is the canonical "
            "deleted state — preserves comments, timer entries, and history.)"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error deleting task: {exc}"


def add_task_comment(agent, params: Any) -> str:
    """Add a comment to a task. Optionally reply to a parent comment.

    Authored by the agent's resolved user (``_resolve_user``) — falls
    back to the workspace's default AI teammate when no user context is
    available.
    """
    from infrastructure.persistence.project.models import TaskComment

    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")
        comment_text = (data.get("comment") or data.get("text") or "").strip()
        parent_id = data.get("parent_comment_id") or data.get("parent_id")

        task, err = _resolve_task_for_update(agent, task_id)
        if err:
            return err

        if not comment_text:
            return "comment text is required."
        if len(comment_text) > 5000:
            return f"Comment too long ({len(comment_text)} chars, max 5000)."

        author = _resolve_user(agent)
        if author is None:
            return "Could not resolve a user to author the comment."

        parent_comment = None
        if parent_id:
            # TaskComment.id is an integer (Django default PK), so a
            # non-numeric input would raise ValueError before reaching
            # the DB. Treat both shapes as "not found" so the LLM gets
            # a helpful message instead of a Python traceback.
            try:
                parent_pk = int(str(parent_id).strip())
            except (TypeError, ValueError):
                return f"Parent comment {parent_id} not found on task '{task.title}'."
            try:
                parent_comment = TaskComment.objects.get(id=parent_pk, task=task)
            except TaskComment.DoesNotExist:
                return f"Parent comment {parent_id} not found on task '{task.title}'."

        comment = TaskComment.objects.create(
            comment=comment_text,
            task=task,
            author=author,
            parent=parent_comment,
        )
        return (
            f"Added comment {comment.id} to task '{task.title}' "
            f"by {getattr(author, 'email', None) or author.id}: "
            f"{comment_text[:120]!r}"
            + ("…" if len(comment_text) > 120 else "")
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error adding comment: {exc}"


def list_task_comments(agent, params: Any) -> str:
    """List comments on a task, most recent first."""
    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")

        task, err = _resolve_task_for_update(agent, task_id)
        if err:
            return err

        # Eager-load author to avoid an N+1 in the formatter
        # (.claude/rules/performance.md §1).
        comments = task.comments.select_related("author").order_by("-created_on")

        limit = data.get("limit")
        if isinstance(limit, int) and limit > 0:
            comments_limited = comments[:limit]
        else:
            comments_limited = comments[:50]

        rows = list(comments_limited)
        total = comments.count()
        if total == 0:
            return f"No comments on task '{task.title}' yet."

        header = (
            f"Comments on '{task.title}' ({total} total"
            f"{', showing first ' + str(len(rows)) if len(rows) < total else ''}):\n\n"
        )
        lines = [header]
        for c in rows:
            author_label = (
                getattr(c.author, "get_full_name", lambda: None)()
                or getattr(c.author, "email", None)
                or str(c.author_id)
            )
            preview = c.comment if len(c.comment) <= 200 else c.comment[:197] + "…"
            reply_marker = " (reply)" if c.parent_id else ""
            lines.append(
                "• {when}  {author}{reply}\n  {body}\n\n".format(
                    when=c.created_on.strftime("%Y-%m-%d %H:%M"),
                    author=author_label,
                    reply=reply_marker,
                    body=preview,
                )
            )
        return "".join(lines)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error listing comments: {exc}"


# ── Task timer tools (PR-B5) ───────────────────────────────────────────
#
# Henry called these out by name in the GTM lock-down ask. The frontend
# already has timer UI on TaskCard (handleKanbanTaskTimer →
# /project/tasks/timer/{action}_timer/), so these tools wire to the
# same use cases the existing UI drives — no contract drift between
# agent and UI.


def _resolve_user_for_timer(agent):
    """Find the CustomUser the timer should bill against.

    Falls back through the same identifier chain ``_resolve_user``
    uses elsewhere in this module.
    """
    user = _resolve_user(agent)
    if user is None:
        return None, "Could not resolve a user to attribute the timer to."
    return user, ""


def start_task_timer(agent, params: Any) -> str:
    """Start tracking time on a task.

    Wires to ``StartTimerUseCase`` — same use case the frontend's
    play button drives. Idempotent at the use-case level: starting a
    second timer for the same task while one is active raises an error
    the use case surfaces.
    """
    from django.utils import timezone

    from components.workspace.application.providers.time_tracking_provider import (
        TimeTrackingProvider,
    )

    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")
        if not task_id:
            return "task_id is required."

        user, err = _resolve_user_for_timer(agent)
        if err:
            return err

        use_case = TimeTrackingProvider.build_start_timer()
        result = use_case.execute(
            user=user,
            workspace_id=agent.workspace_id,
            task_id=str(task_id).strip(),
            project_id=None,
            now=timezone.now(),
        )
        # ``TimerStartResult`` exposes ``entry`` + the task/project info.
        entry = getattr(result, "entry", None)
        return (
            f"Started timer on task {task_id} "
            f"(entry id={getattr(entry, 'id', '?')}). "
            "Use stop_task_timer to record the elapsed time."
        )
    except LookupError as exc:
        return f"Cannot start timer: {exc}"
    except PermissionError as exc:
        return f"Cannot start timer: {exc}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error starting timer: {exc}"


def stop_task_timer(agent, params: Any) -> str:
    """Stop the currently-running timer on a task.

    Wires to ``StopTimerUseCase`` — same use case the frontend's
    stop button drives. Returns the elapsed minutes that were
    recorded onto the ProjectEntry.
    """
    from django.utils import timezone

    from components.workspace.application.providers.time_tracking_provider import (
        TimeTrackingProvider,
    )

    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")
        if not task_id:
            return "task_id is required."

        user, err = _resolve_user_for_timer(agent)
        if err:
            return err

        use_case = TimeTrackingProvider.build_stop_timer()
        result = use_case.execute(
            user=user,
            task_id=str(task_id).strip(),
            project_id=None,
            now=timezone.now(),
        )
        tracked_minutes = getattr(result, "tracked_minutes", None)
        return (
            f"Stopped timer on task {task_id}. "
            f"Recorded {tracked_minutes} minute(s) of tracked time."
        )
    except LookupError as exc:
        return f"Cannot stop timer: {exc}"
    except PermissionError as exc:
        return f"Cannot stop timer: {exc}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error stopping timer: {exc}"


def get_task_timer_status(agent, params: Any) -> str:
    """Report whether a timer is running on a task plus total tracked time.

    Reads ``find_active_entry`` and ``total_tracked_minutes_for_task``
    directly from the time-tracking repository — no use case needed
    for a pure read.
    """
    from django.utils import timezone

    from components.workspace.infrastructure.repositories.time_tracking_repository import (
        OrmTimeTrackingRepository,
    )

    try:
        data = _coerce_payload(params)
        task_id = data.get("task_id")
        if not task_id:
            return "task_id is required."

        # Confirm the task exists in this workspace before looking up
        # tracking data — protects against cross-workspace leakage.
        task, err = _resolve_task_for_update(agent, task_id)
        if err:
            return err

        user, err = _resolve_user_for_timer(agent)
        if err:
            return err

        port = OrmTimeTrackingRepository()
        team = port.resolve_active_team_for_timer(user=user)

        active_entry = port.find_active_entry(
            team_id=team.id,
            user=user,
            task_id=task.id,
            project_id=None,
        )
        total_minutes = port.total_tracked_minutes_for_task(
            task_id=task.id, user=user
        )

        if active_entry is None:
            return (
                f"No active timer on task '{task.title}'. "
                f"Total tracked time across all entries: {total_minutes} minute(s)."
            )

        elapsed = max(
            0,
            int((timezone.now() - active_entry.created_at).total_seconds() / 60),
        )
        return (
            f"Timer is RUNNING on task '{task.title}'. "
            f"Started: {active_entry.created_at.strftime('%Y-%m-%d %H:%M')} "
            f"({elapsed} minute(s) elapsed so far). "
            f"Total tracked across all entries: {total_minutes} minute(s)."
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error reading timer status: {exc}"
