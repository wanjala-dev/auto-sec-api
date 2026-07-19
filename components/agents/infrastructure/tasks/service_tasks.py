"""
Task-related services: creation, querying by status, user completions.
"""
from datetime import timedelta
from typing import List, Optional, Tuple
from django.utils import timezone
from django.db.models import Count, Q

from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.project.models import Project, Task, Column
from infrastructure.persistence.team.models import Team


def find_user(identifier: str) -> Optional[CustomUser]:
    ident = (identifier or '').strip()
    if not ident:
        return None
    # Try email first
    user = CustomUser.objects.filter(email__iexact=ident).first()
    if user:
        return user
    # Try name parts "First Last"
    parts = [p for p in ident.split() if p]
    if len(parts) == 1:
        return CustomUser.objects.filter(Q(first_name__iexact=parts[0]) | Q(last_name__iexact=parts[0])).first()
    if len(parts) >= 2:
        return CustomUser.objects.filter(first_name__iexact=parts[0], last_name__iexact=parts[-1]).first()
    return None


def find_project(workspace_id: str, name: str) -> Optional[Project]:
    if not name:
        return None
    return Project.objects.filter(workspace_id=workspace_id, title__iexact=name).first()


def get_team_for_workspace_or_project(workspace_id: str, project: Optional[Project]) -> Optional[Team]:
    if project and project.team:
        return project.team
    return Team.objects.filter(workspace_id=workspace_id, status=Team.ACTIVE).first() or Team.objects.filter(workspace_id=workspace_id).first()


def parse_task_title(query: str) -> str:
    text = (query or '').strip()
    title = text
    # Try to extract after common stems
    for key in [
        "task to",
        "task for",
        "create a task to",
        "create a task for",
        "add a task to",
        "add a task for",
        "make a task to",
        "make a task for",
    ]:
        idx = text.lower().find(key)
        if idx != -1:
            phrase = text[idx + len(key):].strip()
            if phrase:
                title = phrase
                break
    return title[:255]


def parse_status_from_text(text: str) -> str:
    t = (text or '').lower()
    # Map natural language to Task status constants
    if any(k in t for k in ["done", "completed", "complete"]):
        return Task.DONE
    if any(k in t for k in ["archive", "archived"]):
        return Task.ARCHIVED
    # Treat "in progress", "start", or defaults as TODO
    return Task.TODO


def ensure_default_columns(project: Project) -> dict:
    """Ensure a basic set of columns exists for a project and return a map by title."""
    default = [
        ("Backlog", 0),
        ("In Progress", 1),
        ("Done", 2),
    ]
    existing = {c.title: c for c in Column.objects.filter(project=project)}
    for title, order in default:
        if title not in existing:
            col = Column.objects.create(
                project=project,
                title=title,
                order=order,
                workspace=project.workspace,
                team=project.team,
                created_by=project.created_by,
            )
            existing[title] = col
    return existing


def choose_column_for_status(columns: dict, status: str) -> Optional[Column]:
    if status == Task.DONE:
        return columns.get("Done")
    if status == Task.TODO:
        # Use In Progress as the working column; Backlog otherwise
        return columns.get("In Progress") or columns.get("Backlog")
    # Archived tasks do not need a board column necessarily
    return None


def create_task(workspace_id: str, query: str, creator: CustomUser, project_name: Optional[str], assignee_identifier: Optional[str]) -> Task:
    proj = find_project(workspace_id, project_name) if project_name else None
    team = get_team_for_workspace_or_project(workspace_id, proj)
    if not team:
        raise ValueError("No team found for this workspace. Please create a team first, then create a task.")
    title = parse_task_title(query)
    normalized_title = (title or '').strip().lower()
    normalized_query = (query or '').strip().lower()
    generic_patterns = [
        "create a task",
        "add a task",
        "make a task",
        "help me create a task",
        "help me add a task",
        "help me make a task",
        "can you create a task",
        "can you help me create a task",
        "can you help us create a task",
    ]
    if (
        not normalized_title
        or any(pattern in normalized_title for pattern in generic_patterns)
        or (normalized_title == normalized_query and " task" in normalized_query and " to " not in normalized_query)
    ):
        raise ValueError(
            "Please describe the task you want to create (what needs to be done, optional assignee/project) so I can set it up."
        )
    status = parse_status_from_text(query)
    task = Task.objects.create(
        workspace_id=workspace_id,
        team=team,
        project=proj,
        title=title,
        created_by=creator,
        status=status,
    )
    # Place in a sensible column for the project
    if proj:
        cols = ensure_default_columns(proj)
        col = choose_column_for_status(cols, status)
        if col:
            task.column = col
            task.save(update_fields=["column"])
    if assignee_identifier:
        user = find_user(assignee_identifier)
        if user:
            task.assigned_to.add(user)
    return task


def tasks_in_progress(workspace_id: str, limit: int = 20) -> List[Task]:
    # Interpret "in progress" as TODO (working queue)
    return list(Task.objects.filter(workspace_id=workspace_id, status=Task.TODO).order_by('-created_at')[:limit])


def tasks_by_status(workspace_id: str, status: str, project_name: Optional[str] = None, limit: int = 50) -> List[Task]:
    q = Task.objects.filter(workspace_id=workspace_id, status=status)
    if project_name:
        proj = find_project(workspace_id, project_name)
        if proj:
            q = q.filter(project=proj)
    return list(q.order_by('-updated_at')[:limit])


def create_tasks_for_top_projects(
    workspace_id: str,
    creator: CustomUser,
    base_query: str,
    max_projects: int = 3,
    title_template: str = "This week: {project} deliverables",
) -> List[Task]:
    """Create one TODO task per top-N recent projects for a workspace.

    - Attaches each task to the project's team and project board
    - Places in a sensible column (In Progress/Backlog)
    - Assigns to creator (since phrasing often implies 'for me')
    """
    projects = list(Project.objects.filter(workspace_id=workspace_id).order_by('-created_at')[:max_projects])
    created: List[Task] = []
    for proj in projects:
        title = title_template.format(project=proj.title)[:255]
        t = Task.objects.create(
            workspace_id=workspace_id,
            team=proj.team,
            project=proj,
            title=title,
            created_by=creator,
            status=Task.TODO,
        )
        cols = ensure_default_columns(proj)
        col = choose_column_for_status(cols, Task.TODO)
        if col:
            t.column = col
            t.save(update_fields=["column"])
        t.assigned_to.add(creator)
        created.append(t)
    return created


def user_completed_tasks(workspace_id: str, user_identifier: str, delta: timedelta = timedelta(days=7)) -> Tuple[List[Task], Optional[CustomUser]]:
    user = find_user(user_identifier)
    if not user:
        return [], None
    start = timezone.now() - delta
    qs = Task.objects.filter(
        workspace_id=workspace_id,
        status=Task.DONE,
        updated_at__gte=start,
        assigned_to=user,
    ).order_by('-updated_at')
    return list(qs), user


def tasks_completed(workspace_id: str, delta: timedelta = timedelta(days=7)) -> List[Task]:
    """All tasks marked DONE in the time window for a workspace."""
    start = timezone.now() - delta
    return list(
        Task.objects.filter(workspace_id=workspace_id, status=Task.DONE, updated_at__gte=start).order_by('-updated_at')
    )


def pick_task_for_assignment(workspace_id: str, project_name: Optional[str] = None) -> Optional[Task]:
    """Choose a TODO task to assign:
    - Prefer tasks with no assignees
    - Most recently updated first
    - Optionally restricted to a project
    """
    q = Task.objects.filter(workspace_id=workspace_id, status=Task.TODO)
    if project_name:
        proj = find_project(workspace_id, project_name)
        if not proj:
            return None
        q = q.filter(project=proj)
    q = q.annotate(assign_count=Count('assigned_to')).order_by('assign_count', '-updated_at')
    return q.first()


def assign_task_to_user(task: Task, user: CustomUser) -> Task:
    task.assigned_to.add(user)
    # Move to In Progress column if project present and no column set
    if task.project and not task.column:
        cols = ensure_default_columns(task.project)
        col = choose_column_for_status(cols, Task.TODO)
        if col:
            task.column = col
            task.save(update_fields=["column"])
    return task


def assign_me_a_task(workspace_id: str, user: CustomUser, project_name: Optional[str] = None) -> Optional[Task]:
    t = pick_task_for_assignment(workspace_id, project_name)
    if not t:
        return None
    return assign_task_to_user(t, user)
