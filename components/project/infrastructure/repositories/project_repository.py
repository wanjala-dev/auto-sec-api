"""ORM adapter for project queries (non-creation).

Extracted from project_controller.py to decouple controller from Django ORM.
Uses lazy imports for all model classes.
"""

from __future__ import annotations


class ProjectRepository:
    """Repository for project queries."""

    def get_workspace_by_id(self, workspace_id: str):
        """Fetch workspace by ID. Raises Workspace.DoesNotExist if not found."""
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.get(id=workspace_id)

    def get_team_by_id(self, team_id: str, *, workspace_id: str = None, status: str = None):
        """Fetch team by ID with optional filters.

        Raises Team.DoesNotExist if not found.
        """
        from infrastructure.persistence.team.models import Team

        filters = {"pk": team_id}
        if workspace_id:
            filters["workspace_id"] = workspace_id
        if status:
            filters["status"] = status

        return Team.objects.select_related("workspace", "plan").get(**filters)

    def get_project_by_id(self, project_id: str):
        """Fetch project by ID. Raises Project.DoesNotExist if not found."""
        from infrastructure.persistence.project.models import Project

        return Project.objects.select_related("workspace", "team").get(pk=project_id)

    def get_task_by_id(self, task_id: str):
        """Fetch task by ID with relations. Raises Task.DoesNotExist if not found."""
        from infrastructure.persistence.project.models import Task

        return Task.objects.select_related("workspace", "team", "column", "project").get(pk=task_id)

    def get_column_by_id(self, column_id: str):
        """Fetch column by ID. Raises Column.DoesNotExist if not found."""
        from infrastructure.persistence.project.models import Column

        return Column.objects.get(pk=column_id)

    def get_project_update_by_id(self, update_id: str):
        """Fetch project update by ID. Raises ProjectUpdate.DoesNotExist if not found."""
        from infrastructure.persistence.project.models import ProjectUpdate

        return ProjectUpdate.objects.get(pk=update_id)

    def get_milestone_by_id(self, milestone_id: str):
        """Fetch milestone by ID. Raises ProjectMilestone.DoesNotExist if not found."""
        from infrastructure.persistence.project.models import ProjectMilestone

        return ProjectMilestone.objects.get(pk=milestone_id)

    def get_task_comment_by_id(self, comment_id: str):
        """Fetch task comment by ID. Raises TaskComment.DoesNotExist if not found."""
        from infrastructure.persistence.project.models import TaskComment

        return TaskComment.objects.select_related("author", "task").get(pk=comment_id)

    def list_projects_for_workspace_and_team(self, workspace_id: str, team_id: str):
        """List projects filtered by workspace and team with prefetched tasks."""
        from django.db.models import Prefetch

        from infrastructure.persistence.project.models import Project, Task

        task_prefetch = Prefetch(
            "tasks",
            queryset=Task.objects.select_related("column")
            .prefetch_related("assigned_to__profile", "assigned_to")
            .order_by("order", "created_at"),
        )
        return Project.objects.filter(workspace_id=workspace_id, team_id=team_id, is_deleted=False).prefetch_related(
            task_prefetch
        )

    def list_projects_for_workspace(self, workspace_id: str):
        """List projects for a workspace with prefetched tasks."""
        from django.db.models import Prefetch

        from infrastructure.persistence.project.models import Project, Task

        task_prefetch = Prefetch(
            "tasks",
            queryset=Task.objects.select_related("column")
            .prefetch_related("assigned_to__profile", "assigned_to")
            .order_by("order", "created_at"),
        )
        return Project.objects.filter(workspace_id=workspace_id, is_deleted=False).prefetch_related(task_prefetch)

    def list_projects_for_team(self, team_id: str):
        """List projects for a team with prefetched tasks."""
        from django.db.models import Prefetch

        from infrastructure.persistence.project.models import Project, Task

        task_prefetch = Prefetch(
            "tasks",
            queryset=Task.objects.select_related("column")
            .prefetch_related("assigned_to__profile", "assigned_to")
            .order_by("order", "created_at"),
        )
        return Project.objects.filter(team_id=team_id, is_deleted=False).prefetch_related(task_prefetch)

    def list_projects_for_team_by_team_object(self, team):
        """List projects for a team object with prefetched tasks."""
        from django.db.models import Prefetch

        from infrastructure.persistence.project.models import Task

        task_prefetch = Prefetch(
            "tasks",
            queryset=Task.objects.select_related("column")
            .prefetch_related("assigned_to__profile", "assigned_to")
            .order_by("order", "created_at"),
        )
        return team.projects.filter(is_deleted=False).prefetch_related(task_prefetch)

    def list_tasks_for_team_and_workspace(self, team_id: str, workspace_id: str):
        """List a team's board tasks, excluding soft-deleted (archived) ones.

        ``status=ARCHIVED`` is the Task soft-delete state (there is no
        ``is_deleted`` flag) — a task trashed to the recycle bin must drop off
        the board immediately, not just when its column happens to be hidden.
        """
        from infrastructure.persistence.project.models import Task

        return Task.objects.filter(team_id=team_id, workspace_id=workspace_id).exclude(status=Task.ARCHIVED)

    def list_tasks_assigned_to_user(self, workspace_id: str, assignee_id: str):
        """List a user's assigned tasks in a workspace, across ALL teams.

        Powers the "My Work" surface. Scopes to one workspace and to the
        tasks the given user is assigned to (``assigned_to`` M2M), spanning
        every team in that workspace. Excludes soft-deleted tasks — the
        project context soft-deletes a Task by moving it to
        ``status=ARCHIVED`` (there is no ``is_deleted`` flag on Task),
        mirroring ``archive_tasks_for_column`` and the at-risk detector.

        Eager-loads the relations ``TaskSerializer`` reads so the list
        response is free of N+1s on team / workspace / project / column /
        created_by / assigned_to / entries.
        """
        from infrastructure.persistence.project.models import Task

        return (
            Task.objects.filter(workspace_id=workspace_id, assigned_to__id=assignee_id)
            .exclude(status=Task.ARCHIVED)
            .select_related("team", "workspace", "project", "column", "created_by")
            .prefetch_related("assigned_to__profile", "assigned_to", "entries")
            .order_by("order", "-created_at")
        )

    def list_tasks_for_project(self, project_id: str, status: str = None):
        """List tasks for a project, optionally filtered by status."""
        import json

        from infrastructure.persistence.project.models import Task

        filters = {"project_id": project_id}
        if status:
            filters["status"] = status

        # Return as JSON strings (legacy behavior)
        from django.core.serializers import serialize

        return json.loads(serialize("json", Task.objects.filter(**filters)))

    def list_project_updates_for_project(self, project_id: str):
        """List project updates for a project."""
        from infrastructure.persistence.project.models import ProjectUpdate

        return ProjectUpdate.objects.filter(project_id=project_id)

    def list_milestones_for_project(self, project_id: str):
        """List milestones for a project."""
        from infrastructure.persistence.project.models import ProjectMilestone

        return ProjectMilestone.objects.filter(projects=project_id)

    def get_users_to_assign(self, user_ids: list):
        """Fetch users by IDs."""
        from infrastructure.persistence.users.models import CustomUser

        return CustomUser.objects.filter(id__in=user_ids)

    def create_project_entry(self, **kwargs):
        """Create a project entry (time tracking)."""
        from infrastructure.persistence.project.models import ProjectEntry

        return ProjectEntry.objects.create(**kwargs)

    def archive_tasks_for_column(self, column_id: str):
        """Archive all tasks in a column (when column is soft-deleted)."""
        from infrastructure.persistence.project.models import Task

        return Task.objects.filter(column_id=column_id).update(status=Task.ARCHIVED)
