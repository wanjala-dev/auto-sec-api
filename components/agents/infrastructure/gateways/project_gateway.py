"""
Project helpers for creating workspace projects from natural language queries.
"""

from django.db import transaction

from infrastructure.persistence.project.models import (
    Priority as ProjectPriority,
)
from infrastructure.persistence.project.models import (
    Project,
    Task,
)
from infrastructure.persistence.project.models import (
    Status as ProjectStatus,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace


def extract_project_title(query: str) -> str:
    text = (query or "").strip()
    title = "New Project"
    for key in [
        "project to",
        "project for",
        "create a project to",
        "create a project for",
        "start a project to",
        "start a project for",
    ]:
        idx = text.lower().find(key)
        if idx != -1:
            phrase = text[idx + len(key) :].strip()
            if phrase:
                title = phrase[:120].rstrip(".")
                title = title[:1].upper() + title[1:]
                break
    return title


def ensure_unique_title(workspace_id: str, title: str) -> str:
    base = title
    i = 2
    while Project.objects.filter(workspace_id=workspace_id, title=title).exists():
        title = f"{base} ({i})"
        i += 1
    return title


@transaction.atomic
def create_project(workspace_id: str, user, query: str) -> tuple[Project, Team]:
    team = (
        Team.objects.filter(workspace_id=workspace_id, status=Team.ACTIVE).exclude(kind=Team.Kind.AI_AGENTS).first()
    ) or Team.objects.filter(workspace_id=workspace_id).exclude(kind=Team.Kind.AI_AGENTS).first()
    if not team:
        raise ValueError("No team found for this workspace. Please create a team first, then create a project.")

    title = ensure_unique_title(workspace_id, extract_project_title(query))
    workspace_obj = Workspace.objects.get(id=workspace_id)
    workspace_context = workspace_obj.shared_body or workspace_obj.workspace_story or ""
    description = f"{query.strip()}\n\nContext: {workspace_context}" if workspace_context else query.strip()

    proj = Project.objects.create(
        workspace_id=workspace_id,
        team=team,
        title=title,
        created_by=user,
        description=description,
    )
    return proj, team


# -------- Project analytics/helpers --------


def project_task_counts(project: Project) -> dict[str, int]:
    q = Task.objects.filter(project=project)
    return {
        "total": q.count(),
        "todo": q.filter(status=Task.TODO).count(),
        "done": q.filter(status=Task.DONE).count(),
        "archived": q.filter(status=Task.ARCHIVED).count(),
    }


def set_project_lead(project: Project, user) -> Project:
    project.lead = user
    project.save(update_fields=["lead"])
    return project


def set_project_team(project: Project, team: Team) -> Project:
    if str(team.workspace_id) != str(project.workspace_id):
        raise ValueError("Team must belong to the same workspace as the project")
    project.team = team
    project.save(update_fields=["team"])
    return project


def set_due_date(project: Project, date) -> Project:
    project.end_date = date
    project.save(update_fields=["end_date"])
    return project


def set_status(project: Project, status_code: str) -> Project:
    valid = {c[0] for c in ProjectStatus.choices}
    if status_code not in valid:
        raise ValueError("Invalid project status")
    project.status = status_code
    project.save(update_fields=["status"])
    return project


def set_priority(project: Project, priority_code: str) -> Project:
    valid = {c[0] for c in ProjectPriority.choices}
    if priority_code not in valid:
        raise ValueError("Invalid project priority")
    project.priority = priority_code
    project.save(update_fields=["priority"])
    return project


def resolve_status(text: str) -> str | None:
    t = (text or "").lower()
    mapping = {
        "backlog": ProjectStatus.BACKLOG,
        "think": ProjectStatus.THINK,
        "prototype": ProjectStatus.PROTOTYPE,
        "build": ProjectStatus.BUILD,
        "release": ProjectStatus.RELEASE,
        "tweak": ProjectStatus.TWEAK,
        "completed": ProjectStatus.COMPLETED,
        "complete": ProjectStatus.COMPLETED,
        "done": ProjectStatus.COMPLETED,
        "canceled": ProjectStatus.CANCELED,
        "cancelled": ProjectStatus.CANCELED,
        "cancel": ProjectStatus.CANCELED,
    }
    for key, code in mapping.items():
        if key in t:
            return code
    return None


def resolve_priority(text: str) -> str | None:
    t = (text or "").lower()
    mapping = {
        "no priority": ProjectPriority.NO_PRIORITY,
        "urgent": ProjectPriority.URGENT,
        "high": ProjectPriority.HIGH,
        "medium": ProjectPriority.MEDIUM,
        "low": ProjectPriority.LOW,
    }
    for key, code in mapping.items():
        if key in t:
            return code
    return None
