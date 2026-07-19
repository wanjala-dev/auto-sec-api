"""Reusable project management agent tools."""

from __future__ import annotations

import ast
import json
import logging
import re
import uuid
from datetime import date, datetime
from typing import Any


def _coerce_payload(payload: Any) -> dict[str, Any]:
    """Coerce tool input into a dict. Accepts None, dict, or JSON string."""
    if payload in (None, "", {}):
        return {}
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return {}
        match = re.search(r"\b\w+\s*[:=]\s*(\{.*\})", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        def _coerce_js_object(raw: str) -> str:
            fixed = raw.strip()
            if fixed and fixed[0] != "{":
                fixed = "{" + fixed + "}"
            if "'" in fixed and '"' not in fixed:
                fixed = fixed.replace("'", '"')
            fixed = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', fixed)
            return fixed

        try:
            return json.loads(text)
        except Exception:  # pylint: disable=broad-except
            try:
                return json.loads(_coerce_js_object(text))
            except Exception:  # pylint: disable=broad-except
                try:
                    parsed = ast.literal_eval(text)
                except Exception:  # pylint: disable=broad-except
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
                # Treat plain text as a project name/prompt
                return {"name": text}
    if isinstance(payload, dict):
        return payload
    raise ValueError("Tool input must be a JSON string or dictionary.")


def _extract_prompt(payload: Any) -> str:
    if payload in (None, ""):
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("prompt", "query", "name", "title", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_project_name(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"\bproject\s+([A-Za-z0-9][A-Za-z0-9\s'\-]+)", text, re.IGNORECASE)
    if not match:
        return ""
    candidate = match.group(1)
    candidate = re.split(
        r"\b(this|last|current|quarter|month|year|today)\b", candidate, maxsplit=1, flags=re.IGNORECASE
    )[0]
    candidate = candidate.split("?")[0].split(".")[0].strip()
    return candidate.strip("'\"“”‘’")


def _is_confirmed(data: dict[str, Any]) -> bool:
    value = data.get("confirm")
    if value is None:
        value = data.get("confirmed") or data.get("confirmation")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "confirmed", "sure"}
    return False


def _confirmation_message() -> str:
    return (
        "Project creation requires explicit confirmation. "
        "Retry the tool with `confirm: true` (and include the project details) once you are sure."
    )


def _format_project_listing(agent, limit: int = 10) -> str:
    from infrastructure.persistence.project.models import Project

    qs = Project.objects.filter(workspace_id=agent.workspace_id).order_by("-created_at")
    if limit and limit > 0:
        qs = qs[:limit]
    if not qs.exists():
        return "No projects found for this workspace."
    names = ", ".join(project.title for project in qs)
    return f"Available projects: {names}"


def _parse_date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _parse_period(value: Any) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    if "quarter" in text:
        return "quarter"
    if "month" in text:
        return "month"
    if "year" in text:
        return "year"
    return ""


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _resolve_user_id(agent, data: dict) -> str:
    """Return a validated user ID string, falling back to the agent user."""
    from uuid import UUID

    candidate = data.get("user_id") or data.get("requester_id") or data.get("requested_by")
    if not candidate:
        return str(agent.user_id)
    try:
        return str(UUID(str(candidate)))
    except (ValueError, TypeError, AttributeError):
        return str(agent.user_id)


def _user_has_workspace_access(workspace, user_id: str) -> bool:
    """Return True when the user is a workspace owner/member (excluding AI-only teams)."""
    from infrastructure.persistence.team.models import Team
    from infrastructure.persistence.users.models import CustomUser
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    user = CustomUser.objects.filter(id=user_id).first()
    if not user:
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    if str(workspace.workspace_owner_id) == str(user.id):
        return True
    if WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=user,
        status=WorkspaceMembership.Status.ACTIVE,
    ).exists():
        return True
    return (
        Team.objects.filter(
            workspace=workspace,
            status=Team.ACTIVE,
            members__id=user.id,
        )
        .exclude(kind=Team.Kind.AI_AGENTS)
        .exists()
    )


def _has_action_access(workspace, user_id: str, action: str, *, scope_type=None, scope_id=None) -> bool:
    from components.agents.application.facades.agent_permissions_facade import ai_can

    if _user_has_workspace_access(workspace, user_id):
        return True
    return ai_can(
        str(workspace.id),
        user_id,
        action=action,
        scope_type=scope_type,
        scope_id=scope_id,
    )


def get_project_info(agent, project_identifier: str) -> str:
    from infrastructure.persistence.project.models import Project

    try:
        if not project_identifier:
            return f"Please specify a project name or ID.\n{_format_project_listing(agent)}"

        if project_identifier.isdigit():
            project = Project.objects.filter(id=project_identifier, workspace_id=agent.workspace_id).first()
        else:
            project = Project.objects.filter(
                title__icontains=project_identifier, workspace_id=agent.workspace_id
            ).first()

        if not project:
            return f"Project '{project_identifier}' not found.\n{_format_project_listing(agent)}"

        team_members = project.team_members.all() if hasattr(project, "team_members") else []
        member_names = ", ".join(member.name for member in team_members) or "None"
        tasks_count = project.tasks.count() if hasattr(project, "tasks") else 0
        return (
            "Project Information:\n"
            f"Name: {project.title}\n"
            f"Description: {project.description or 'No description'}\n"
            f"Status: {project.status}\n"
            f"Progress: {getattr(project, 'progress_percentage', 0)}%\n"
            f"Start Date: {project.start_date or 'Not set'}\n"
            f"End Date: {project.end_date or 'Not set'}\n"
            f"Budget: ${project.budget:.2f}\n"
            f"Team Members: {len(team_members)} ({member_names})\n"
            f"Tasks: {tasks_count}\n"
            f"Created: {project.created_at.strftime('%Y-%m-%d')}\n"
            f"Last Updated: {project.updated_at.strftime('%Y-%m-%d')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error retrieving project info: {exc}"


def list_projects(agent, params: Any) -> str:
    """List projects for the current workspace with optional filters (status, limit)."""
    from infrastructure.persistence.project.models import Project

    try:
        data = _coerce_payload(params)

        # Require workspace context to scope listing
        if not getattr(agent, "workspace_id", None):
            return (
                "No workspace context available for this agent. "
                "Please create or assign the agent to a workspace before listing projects."
            )

        qs = Project.objects.filter(workspace_id=agent.workspace_id)
        if status := data.get("status"):
            qs = qs.filter(status=status)
        limit = data.get("limit")
        if isinstance(limit, int) and limit > 0:
            qs = qs.order_by("-created_at")[:limit]
        else:
            qs = qs.order_by("-created_at")

        count = qs.count()
        if count == 0:
            return "No projects found for this workspace."

        lines = [f"Projects ({count}):\n\n"]
        for p in qs:
            lines.append(
                "• {name}\n  Status: {status}\n  Budget: ${budget:.2f}\n  Progress: {progress}%\n  Created: {created}\n\n".format(
                    name=p.title,
                    status=p.status,
                    budget=getattr(p, "budget", 0) or 0,
                    progress=getattr(p, "progress_percentage", 0) or 0,
                    created=p.created_at.strftime("%Y-%m-%d"),
                )
            )
        return "".join(lines)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error listing projects: {exc}"


def update_project_status(agent, update_data: Any) -> str:
    """Compatibility shim — delegates to ``update_project``.

    The original implementation referenced ``project.notes``,
    ``project.progress_percentage``, and ``project.updated_at`` —
    none of which exist on the Project model. Callers should use
    ``update_project`` directly going forward; this stub is kept
    only because the agent surface still registers it (will be
    removed in a follow-up).
    """
    return update_project(agent, update_data)


def assign_project_team(agent, assignment_data: Any) -> str:
    from django.contrib.auth import get_user_model

    from infrastructure.persistence.project.models import Project

    try:
        data = _coerce_payload(assignment_data)
        project = Project.objects.get(id=data["project_id"], workspace_id=agent.workspace_id)
        team_member_ids = data["team_member_ids"]
        User = get_user_model()
        assigned_members = []
        for member_id in team_member_ids:
            try:
                member = User.objects.get(id=member_id)
                project.team_members.add(member)
                assigned_members.append(member.name)
            except Exception:  # pylint: disable=broad-except
                continue
        return (
            "Team Assignment Complete:\n"
            f"Project: {project.title}\n"
            f"Assigned Members: {', '.join(assigned_members) if assigned_members else 'None'}\n"
            f"Total Team Size: {project.team_members.count()}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error assigning project team: {exc}"


def create_project_task(agent, task_data: Any) -> str:
    from django.contrib.auth import get_user_model

    from infrastructure.persistence.project.models import Project, Task

    try:
        data = _coerce_payload(task_data)
        project = Project.objects.get(id=data["project_id"], workspace_id=agent.workspace_id)
        assignee = None
        if data.get("assignee_id"):
            User = get_user_model()
            assignee = User.objects.get(id=data["assignee_id"])
        task = Task.objects.create(
            project=project,
            title=data["title"],
            description=data.get("description", ""),
            assignee=assignee,
            due_date=data.get("due_date"),
            status="pending",
            priority=data.get("priority", "medium"),
            workspace_id=agent.workspace_id,
        )
        return (
            "Task Created Successfully:\n"
            f"ID: {task.id}\n"
            f"Title: {task.title}\n"
            f"Project: {project.title}\n"
            f"Assignee: {assignee.name if assignee else 'Unassigned'}\n"
            f"Due Date: {task.due_date or 'Not set'}\n"
            f"Status: {task.status}\n"
            f"Priority: {task.priority}\n"
            f"Created: {task.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error creating project task: {exc}"


def get_project_tasks(agent, query: Any) -> str:
    from infrastructure.persistence.project.models import Project

    try:
        data = _coerce_payload(query)
        project = Project.objects.get(id=data["project_id"], workspace_id=agent.workspace_id)
        tasks = project.tasks.all()
        if data.get("status_filter"):
            tasks = tasks.filter(status=data["status_filter"])
        if not tasks.exists():
            return f"No tasks found for project '{project.title}'"
        lines = [f"Project Tasks: {project.title} ({tasks.count()} tasks)\n\n"]
        for task in tasks:
            lines.append(
                "• {title}\n  Status: {status}\n  Priority: {priority}\n  Assignee: {assignee}\n  Due Date: {due}\n  Created: {created}\n  \n".format(
                    title=task.title,
                    status=task.status,
                    priority=task.priority,
                    assignee=task.assignee.name if task.assignee else "Unassigned",
                    due=task.due_date or "Not set",
                    created=task.created_at.strftime("%Y-%m-%d"),
                )
            )
        return "".join(lines)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error retrieving project tasks: {exc}"


def update_task_status(agent, update_data: Any) -> str:
    from infrastructure.persistence.project.models import Task

    try:
        data = _coerce_payload(update_data)
        task = Task.objects.get(id=data["task_id"], workspace_id=agent.workspace_id)
        if "status" in data:
            task.status = data["status"]
        if "progress_percentage" in data:
            task.progress_percentage = data["progress_percentage"]
        if "notes" in data:
            task.notes = data["notes"]
        task.save()
        return (
            "Task Updated:\n"
            f"Title: {task.title}\n"
            f"Status: {task.status}\n"
            f"Progress: {getattr(task, 'progress_percentage', 0)}%\n"
            f"Notes: {getattr(task, 'notes', 'No notes')}\n"
            f"Updated: {task.updated_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error updating task status: {exc}"


def get_project_timeline(agent, params: Any) -> str:
    """Render a project's timeline + attached milestones.

    ``ProjectMilestone`` uses ``target_date`` (not ``due_date``) and
    has no ``status`` field — those references in earlier versions of
    this tool would AttributeError. Now reads only fields the model
    actually exposes.
    """
    from django.core.exceptions import ValidationError

    from infrastructure.persistence.project.models import Project

    try:
        data = _coerce_payload(params)
        project_id = str(data.get("project_id") or "").strip()
        if not project_id or project_id.lower() in {"none", "null"}:
            return "project_id is required."

        try:
            project = Project.objects.get(id=project_id, workspace_id=agent.workspace_id)
        except (Project.DoesNotExist, ValidationError, ValueError):
            return f"Project {project_id} not found in this workspace."

        milestones = list(project.milestones.all()) if hasattr(project, "milestones") else []
        lines = [
            f"Project Timeline: {project.title}\n",
            f"Start Date: {project.start_date or 'Not set'}\n",
            f"End Date: {project.end_date or 'Not set'}\n",
            f"Duration: {_calculate_duration(project.start_date, project.end_date)}\n\n",
            f"Milestones ({len(milestones)}):\n",
        ]
        for milestone in milestones:
            lines.append(
                "• {name}\n  Target Date: {target}\n  Description: {description}\n\n".format(
                    name=milestone.name,
                    target=milestone.target_date,
                    description=milestone.description or "No description",
                )
            )
        return "".join(lines)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error retrieving project timeline: {exc}"


def create_project_milestone(agent, params: Any) -> str:
    """Create a milestone and attach it to a project.

    ``ProjectMilestone`` is M2M-attached to projects (no project FK on
    the milestone itself), has no ``status``, no ``workspace`` FK, and
    uses ``target_date`` (not ``due_date``). The previous implementation
    referenced all four nonexistent fields and an imaginary ``Milestone``
    class — all fixed here.
    """
    from datetime import datetime

    from django.core.exceptions import ValidationError

    from infrastructure.persistence.project.models import Project, ProjectMilestone

    try:
        data = _coerce_payload(params)
        project_id = str(data.get("project_id") or "").strip()
        name = str(data.get("name") or "").strip()
        target_raw = data.get("target_date") or data.get("due_date")

        if not project_id:
            return "project_id is required."
        if not name:
            return "name is required."
        if not target_raw:
            return "target_date is required (YYYY-MM-DD)."

        try:
            target_date = datetime.strptime(str(target_raw).strip(), "%Y-%m-%d").date()
        except ValueError:
            return f"Could not parse target_date {target_raw!r}; use YYYY-MM-DD."

        try:
            project = Project.objects.get(id=project_id, workspace_id=agent.workspace_id)
        except (Project.DoesNotExist, ValidationError, ValueError):
            return f"Project {project_id} not found in this workspace."

        creator = _resolve_user(agent)
        milestone = ProjectMilestone.objects.create(
            name=name,
            description=data.get("description", "") or "",
            target_date=target_date,
            creator=creator,
        )
        project.milestones.add(milestone)
        return (
            "Milestone Created Successfully:\n"
            f"ID: {milestone.id}\n"
            f"Name: {milestone.name}\n"
            f"Project: {project.title}\n"
            f"Target Date: {milestone.target_date}\n"
            f"Description: {milestone.description or 'No description'}\n"
            f"Created: {milestone.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error creating project milestone: {exc}"


def get_project_analytics(agent, analytics_params: Any) -> str:
    from infrastructure.persistence.project.models import Project, Task

    try:
        data = _coerce_payload(analytics_params)
        projects = Project.objects.filter(workspace_id=agent.workspace_id)
        if data.get("project_id"):
            projects = projects.filter(id=data["project_id"])

        total_projects = projects.count()
        active_projects = projects.filter(status__in=["planning", "in_progress"]).count()
        completed_projects = projects.filter(status="completed").count()

        tasks_qs = Task.objects.filter(project__in=projects)
        total_tasks = tasks_qs.count()
        completed_tasks = tasks_qs.filter(status="completed").count()
        pending_tasks = tasks_qs.filter(status="pending").count()

        total_budget = sum(project.budget for project in projects)
        completion_rate = (completed_tasks / total_tasks * 100) if total_tasks else 0
        average_budget = (total_budget / total_projects) if total_projects else 0

        return (
            "Project Analytics\n"
            f"Total Projects: {total_projects}\n"
            f"Active Projects: {active_projects}\n"
            f"Completed Projects: {completed_projects}\n\n"
            "Task Statistics:\n"
            f"Total Tasks: {total_tasks}\n"
            f"Completed Tasks: {completed_tasks}\n"
            f"Pending Tasks: {pending_tasks}\n"
            f"Completion Rate: {completion_rate:.1f}%\n\n"
            "Budget Overview:\n"
            f"Total Budget: ${total_budget:.2f}\n"
            f"Average Project Budget: ${average_budget:.2f}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error generating project analytics: {exc}"


def generate_project_report(agent, report_params: Any) -> str:
    from infrastructure.persistence.project.models import Project

    try:
        data = _coerce_payload(report_params)
        project = Project.objects.get(id=data["project_id"], workspace_id=agent.workspace_id)
        report_type = data.get("report_type", "status")
        if report_type == "status":
            return _status_report(project)
        if report_type == "budget":
            return _budget_report(project)
        if report_type == "timeline":
            return _timeline_report(project)
        return _comprehensive_project_report(project)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error generating project report: {exc}"


def manage_project_budget(agent, budget_data: Any) -> str:
    from infrastructure.persistence.project.models import Project

    try:
        data = _coerce_payload(budget_data)
        project = Project.objects.get(id=data["project_id"], workspace_id=agent.workspace_id)
        if "allocated_amount" in data:
            project.budget = data["allocated_amount"]
        if "spent_amount" in data:
            project.spent_amount = data["spent_amount"]
        project.save()
        remaining_budget = project.budget - getattr(project, "spent_amount", 0)
        return (
            "Budget Updated:\n"
            f"Project: {project.title}\n"
            f"Allocated Budget: ${project.budget:.2f}\n"
            f"Spent Amount: ${getattr(project, 'spent_amount', 0):.2f}\n"
            f"Remaining Budget: ${remaining_budget:.2f}\n"
            f"Updated: {project.updated_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error managing project budget: {exc}"


def get_project_risks(agent, project_id: str) -> str:
    from infrastructure.persistence.project.models import Project

    try:
        project = Project.objects.get(id=project_id, workspace_id=agent.workspace_id)
        risks = project.risks.all() if hasattr(project, "risks") else []
        if not risks:
            return f"No risks identified for project '{project.title}'"
        lines = [f"Project Risks: {project.title} ({len(risks)} risks)\n\n"]
        for risk in risks:
            lines.append(
                "• {title}\n  Severity: {severity}\n  Status: {status}\n  Description: {description}\n  Mitigation: {mitigation}\n  \n".format(
                    title=risk.title,
                    severity=risk.severity,
                    status=risk.status,
                    description=risk.description or "No description",
                    mitigation=risk.mitigation or "No mitigation plan",
                )
            )
        return "".join(lines)
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error retrieving project risks: {exc}"


def add_project_risk(agent, risk_data: Any) -> str:
    from infrastructure.persistence.project.models import Project, Risk

    try:
        data = _coerce_payload(risk_data)
        project = Project.objects.get(id=data["project_id"], workspace_id=agent.workspace_id)
        risk = Risk.objects.create(
            project=project,
            title=data["title"],
            description=data.get("description", ""),
            severity=data.get("severity", "medium"),
            mitigation=data.get("mitigation", ""),
            status="open",
            workspace_id=agent.workspace_id,
        )
        return (
            "Risk Added Successfully:\n"
            f"ID: {risk.id}\n"
            f"Title: {risk.title}\n"
            f"Project: {project.title}\n"
            f"Severity: {risk.severity}\n"
            f"Status: {risk.status}\n"
            f"Description: {risk.description or 'No description'}\n"
            f"Mitigation: {risk.mitigation or 'No mitigation plan'}\n"
            f"Created: {risk.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error adding project risk: {exc}"


def check_project_permissions(agent, permission_data: Any) -> str:
    from components.agents.application.facades.agent_permissions_facade import ai_can
    from infrastructure.persistence.ai.models import AIPermissionGrant
    from infrastructure.persistence.project.models import Project
    from infrastructure.persistence.team.models import Team
    from infrastructure.persistence.workspaces.models import Workspace

    try:
        data = _coerce_payload(permission_data)
        workspace = Workspace.objects.get(id=data["workspace_id"])
        user_id = _resolve_user_id(agent, data)
        project_id = data.get("project_id") or data.get("project")
        scope_id = None
        if str(workspace.workspace_owner_id) == user_id:
            return "User has full project access (workspace owner)"
        teams = Team.objects.filter(workspace_id=workspace.id, status="active").exclude(kind=Team.Kind.AI_AGENTS)
        if project_id:
            try:
                project = Project.objects.get(id=project_id, workspace_id=workspace.id)
                scope_id = str(project.team_id)
            except Project.DoesNotExist:
                scope_id = None
        for team in teams:
            if team.members.filter(id=user_id).exists():
                return f"User has project access (member of team: {team.title})"
        if ai_can(
            str(workspace.id),
            user_id,
            action="project:write",
            scope_type=AIPermissionGrant.SCOPE_DEPARTMENT,
            scope_id=scope_id,
        ):
            return "User has project access (AI executor grant)"
        return "User does not have project access"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error checking permissions: {exc}"


def _calculate_duration(start_date, end_date) -> str:
    if not start_date or not end_date:
        return "Duration not calculable"
    try:
        from datetime import datetime

        start = datetime.strptime(str(start_date), "%Y-%m-%d")
        end = datetime.strptime(str(end_date), "%Y-%m-%d")
        return f"{(end - start).days} days"
    except Exception:  # pylint: disable=broad-except
        return "Duration not calculable"


def _status_report(project) -> str:
    tasks = project.tasks.all()
    completed_tasks = tasks.filter(status="completed").count()
    total_tasks = tasks.count()
    return (
        f"Project Status Report: {project.title}\n"
        f"Status: {project.status}\n"
        f"Progress: {getattr(project, 'progress_percentage', 0)}%\n"
        f"Tasks: {completed_tasks}/{total_tasks} completed\n"
        f"Team Size: {project.team_members.count()}\n"
        f"Budget: ${project.budget:.2f}\n"
        f"Timeline: {project.start_date or 'Not set'} to {project.end_date or 'Not set'}"
    )


def _budget_report(project) -> str:
    spent_amount = getattr(project, "spent_amount", 0)
    remaining_budget = project.budget - spent_amount
    utilization = (spent_amount / project.budget * 100) if project.budget else 0
    return (
        f"Project Budget Report: {project.title}\n"
        f"Allocated Budget: ${project.budget:.2f}\n"
        f"Spent Amount: ${spent_amount:.2f}\n"
        f"Remaining Budget: ${remaining_budget:.2f}\n"
        f"Budget Utilization: {utilization:.1f}%"
    )


def _timeline_report(project) -> str:
    return (
        f"Project Timeline Report: {project.title}\n"
        f"Start Date: {project.start_date or 'Not set'}\n"
        f"End Date: {project.end_date or 'Not set'}\n"
        f"Duration: {_calculate_duration(project.start_date, project.end_date)}\n"
        f"Status: {project.status}\n"
        f"Progress: {getattr(project, 'progress_percentage', 0)}%"
    )


def _comprehensive_project_report(project) -> str:
    return (
        f"Comprehensive Project Report: {project.title}\n"
        f"Status: {project.status}\n"
        f"Progress: {getattr(project, 'progress_percentage', 0)}%\n"
        f"Budget: ${project.budget:.2f}\n"
        f"Team Size: {project.team_members.count()}\n"
        f"Tasks: {project.tasks.count()}\n"
        f"Timeline: {project.start_date or 'Not set'} to {project.end_date or 'Not set'}\n"
        f"Created: {project.created_at.strftime('%Y-%m-%d')}"
    )


# ── Project edits + milestone CRUD (PR-C1) ─────────────────────────────


def _resolve_project_for_update(agent, project_id: Any):
    """Look up a Project scoped to the agent's workspace.

    Returns ``(project, error)`` — exactly one is set. Centralises the
    not-found / wrong-workspace path so every update tool emits the
    same error shape rather than a stack trace.
    """
    from django.core.exceptions import ValidationError

    from infrastructure.persistence.project.models import Project

    cleaned = (str(project_id) if project_id is not None else "").strip()
    if not cleaned or cleaned.lower() in {"none", "null", "undefined"}:
        return None, "project_id is required."
    try:
        project = Project.objects.select_related("team", "lead").get(id=cleaned, workspace_id=agent.workspace_id)
        return project, ""
    except (Project.DoesNotExist, ValidationError, ValueError):
        return None, f"Project {cleaned} not found in this workspace."


def update_project(agent, params: Any) -> str:
    """Update fields on an existing project.

    Accepts any subset of: ``title``, ``description``, ``status``,
    ``priority``, ``start_date``, ``end_date`` (YYYY-MM-DD),
    ``resources``, ``lead_user_id``. Pass only the fields you want
    changed.
    """

    try:
        data = _coerce_payload(params)
        project, err = _resolve_project_for_update(agent, data.get("project_id"))
        if err:
            return err

        update_fields: list[str] = []

        # Simple text fields.
        for field in ("title", "description", "resources"):
            if field in data and data[field] is not None:
                value = str(data[field]).strip()
                if field == "title" and not value:
                    return "title cannot be empty."
                if field == "title" and len(value) > 255:
                    return f"title too long ({len(value)} chars, max 255)."
                setattr(project, field, value)
                update_fields.append(field)

        # Status — model uses 2-char choices (BACKLOG, etc.); accept the
        # CharField value directly. Validation lives in the model.
        if "status" in data and data["status"] is not None:
            project.status = str(data["status"]).strip()
            update_fields.append("status")

        # Priority — same idea.
        if "priority" in data and data["priority"] is not None:
            project.priority = str(data["priority"]).strip()
            update_fields.append("priority")

        # Dates — accept YYYY-MM-DD or null to clear.
        for field in ("start_date", "end_date"):
            if field in data:
                raw = data[field]
                if raw in (None, "") or (isinstance(raw, str) and raw.strip().lower() in {"none", "null"}):
                    setattr(project, field, None)
                    update_fields.append(field)
                else:
                    try:
                        parsed = datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
                        setattr(project, field, parsed)
                        update_fields.append(field)
                    except ValueError:
                        return f"Could not parse {field} {raw!r}; use YYYY-MM-DD."

        # Lead — optional FK to user.
        if "lead_user_id" in data or "lead" in data:
            from django.core.exceptions import ValidationError as _VE

            from infrastructure.persistence.users.models import CustomUser

            raw = data.get("lead_user_id") or data.get("lead")
            if raw in (None, "") or (isinstance(raw, str) and raw.strip().lower() in {"none", "null"}):
                project.lead = None
                update_fields.append("lead")
            else:
                try:
                    user = CustomUser.objects.get(id=str(raw).strip())
                    project.lead = user
                    update_fields.append("lead")
                except (CustomUser.DoesNotExist, _VE, ValueError):
                    return f"Lead user {raw!r} not found."

        if not update_fields:
            return "No fields provided to update."

        project.save(update_fields=update_fields)
        lead_label = (project.lead.get_full_name() or project.lead.email) if project.lead else "(unassigned)"
        return (
            f"Updated project '{project.title}' ({len(update_fields)} field(s)):\n"
            f"  Status: {project.status}  Priority: {project.priority}\n"
            f"  Window: {project.start_date or '—'} → {project.end_date or '—'}\n"
            f"  Lead: {lead_label}\n"
            f"  Description: {(project.description or '—')[:200]}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error updating project: {exc}"


def update_project_milestone(agent, params: Any) -> str:
    """Update a milestone attached to a project in this workspace.

    Required: ``milestone_id``, ``project_id`` (the milestone's parent
    project — used to enforce workspace scope, since ``ProjectMilestone``
    has no workspace FK directly). Optional: ``name``, ``description``,
    ``target_date`` (YYYY-MM-DD).
    """
    from infrastructure.persistence.project.models import ProjectMilestone

    try:
        data = _coerce_payload(params)
        project, err = _resolve_project_for_update(agent, data.get("project_id"))
        if err:
            return err

        milestone_id = str(data.get("milestone_id") or "").strip()
        if not milestone_id or milestone_id.lower() in {"none", "null"}:
            return "milestone_id is required."

        # Scope: milestone must belong to this project (M2M).
        try:
            milestone_pk = int(milestone_id)
        except (TypeError, ValueError):
            return f"Milestone id {milestone_id!r} must be an integer."
        try:
            milestone = project.milestones.get(id=milestone_pk)
        except ProjectMilestone.DoesNotExist:
            return f"Milestone {milestone_id} is not attached to project '{project.title}'."

        update_fields: list[str] = []
        if "name" in data and data["name"] is not None:
            value = str(data["name"]).strip()
            if not value:
                return "name cannot be empty."
            if len(value) > 255:
                return f"name too long ({len(value)} chars, max 255)."
            milestone.name = value
            update_fields.append("name")
        if "description" in data and data["description"] is not None:
            milestone.description = str(data["description"]).strip()
            update_fields.append("description")
        if "target_date" in data:
            raw = data["target_date"]
            if raw in (None, "") or (isinstance(raw, str) and raw.strip().lower() in {"none", "null"}):
                return "target_date cannot be cleared (it's required on milestones)."
            try:
                milestone.target_date = datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
                update_fields.append("target_date")
            except ValueError:
                return f"Could not parse target_date {raw!r}; use YYYY-MM-DD."

        if not update_fields:
            return "No fields provided to update."

        milestone.save(update_fields=update_fields)
        return (
            f"Updated milestone '{milestone.name}' on project '{project.title}':\n"
            f"  Target date: {milestone.target_date}\n"
            f"  Description: {(milestone.description or '—')[:200]}"
        )
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error updating milestone: {exc}"


def delete_project_milestone(agent, params: Any) -> str:
    """Delete a milestone from a project.

    Removes the M2M link AND deletes the underlying ``ProjectMilestone``
    row (since the model has no workspace scope and is conceptually
    owned by the project).
    """
    from infrastructure.persistence.project.models import ProjectMilestone

    try:
        data = _coerce_payload(params)
        project, err = _resolve_project_for_update(agent, data.get("project_id"))
        if err:
            return err

        milestone_id = str(data.get("milestone_id") or "").strip()
        if not milestone_id or milestone_id.lower() in {"none", "null"}:
            return "milestone_id is required."
        try:
            milestone_pk = int(milestone_id)
        except (TypeError, ValueError):
            return f"Milestone id {milestone_id!r} must be an integer."
        try:
            milestone = project.milestones.get(id=milestone_pk)
        except ProjectMilestone.DoesNotExist:
            return f"Milestone {milestone_id} is not attached to project '{project.title}'."

        name = milestone.name
        project.milestones.remove(milestone)
        # The milestone is orphaned (M2M only attaches it to projects);
        # delete it so it doesn't pile up in the table.
        if not milestone.projects.exists():
            milestone.delete()
        return f"Deleted milestone '{name}' from project '{project.title}'."
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error deleting milestone: {exc}"


def create_project(agent, project_data: Any) -> str:
    """Create a project over the fork's budget-free ``CreateProjectUseCase``.

    The nonprofit ``plan_and_create_project`` path (which fans out an LLM
    planner and writes budget *estimate transactions*) is intentionally not
    used here — the Auto-Sec fork has no budgeting context, so project creation
    is the simple, direct thing: a titled project on a team. Requires a
    ``confirm`` flag (mirrors the other write tools) and ``project:write``
    access.
    """
    from infrastructure.persistence.workspaces.models import Workspace
    from components.project.application.service import ProjectService
    from components.project.domain.errors import (
        ProjectLimitExceededError,
        TeamMembershipRequiredError,
        TeamNotFoundError,
    )

    try:
        data = _coerce_payload(project_data)
        title = (data.get("name") or data.get("title") or "").strip()
        if not title:
            return "Project name is required. Please provide a project name."
        team_id = data.get("team_id") or data.get("team")
        if not team_id:
            return "A team_id is required to create a project. Use get_team_members or list teams first."
        if not _is_confirmed(data):
            logger.info(
                "[project_agent] blocked create_project for workspace=%s without confirmation (title=%s)",
                agent.workspace_id,
                title,
            )
            return _confirmation_message()

        workspace = Workspace.objects.get(id=agent.workspace_id)
        user_id = _resolve_user_id(agent, data)
        if not _has_action_access(workspace, user_id, "project:write"):
            return "Permission denied: unable to create projects."

        result = ProjectService().create_project(
            title=title,
            team_id=str(team_id),
            user_id=str(agent.user_id),
            workspace_id=str(agent.workspace_id),
            create_dedicated_budget=False,
        )
        project = getattr(result, "project", None) or result
        project_id = getattr(project, "id", None) or getattr(project, "pk", None)
        return f"Project created: '{title}' (id={project_id}) on team {team_id}."
    except TeamNotFoundError:
        return "Team not found — cannot create the project."
    except TeamMembershipRequiredError:
        return "Permission denied: you must be a member of that team to create a project in it."
    except ProjectLimitExceededError as exc:
        return f"Project limit reached: {exc}"
    except Exception as exc:  # pylint: disable=broad-except
        return f"Error creating project: {exc}"
