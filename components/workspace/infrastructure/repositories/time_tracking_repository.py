"""ORM adapter for time-tracking operations.

Extracted from StartTimerView, StopTimerView, DiscardTimerView in project_controller.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Sum

from components.workspace.domain.errors import (
    TeamMembershipRequiredError,
    TeamNotFoundError,
    TeamValidationError,
    WorkspaceNotFoundError,
    WorkspaceValidationError,
)
from components.workspace.application.ports.time_tracking_port import TimeTrackingPort


class OrmTimeTrackingRepository(TimeTrackingPort):

    def validate_workspace(self, workspace_id: Any) -> Any:
        from infrastructure.persistence.workspaces.models import Workspace

        try:
            return Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            raise WorkspaceNotFoundError("Invalid Workspace ID.")

    def resolve_active_team_for_timer(self, *, user: Any) -> Any:
        from infrastructure.persistence.team.models import Team

        profile = getattr(user, "profile", None)
        if not profile or not profile.active_team_id:
            raise TeamValidationError("Set an active team before using timer.")

        team = Team.objects.filter(id=profile.active_team_id, status=Team.ACTIVE).first()
        if not team:
            raise TeamNotFoundError("Active team not found or inactive.")
        return team

    def validate_team_workspace(self, *, team: Any, workspace: Any) -> None:
        if str(team.workspace_id) != str(workspace.id):
            raise TeamValidationError("Active team does not belong to this organization.")

    def validate_team_membership(self, *, user: Any, team: Any, workspace: Any) -> None:
        # Workspace admins/owners bypass team membership (ADR 0002).
        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_admin_or_owner,
        )
        if user_is_workspace_admin_or_owner(user, workspace):
            return
        if not team.members.filter(id=user.id).exists():
            raise TeamMembershipRequiredError("You must be a member of this team to track time.")

    def validate_task(self, *, task_id: Any, workspace: Any) -> Any:
        if task_id is None:
            return None
        from infrastructure.persistence.project.models import Task

        try:
            task = Task.objects.select_related("workspace", "project").get(id=task_id)
        except Task.DoesNotExist:
            raise WorkspaceNotFoundError("Invalid Task ID.")
        if str(task.workspace_id) != str(workspace.id):
            raise WorkspaceValidationError("Task does not belong to this organization.")
        return task

    def validate_project(self, *, project_id: Any, workspace: Any) -> Any:
        if project_id is None:
            return None
        from infrastructure.persistence.project.models import Project

        try:
            project = Project.objects.select_related("workspace").get(id=project_id)
        except Project.DoesNotExist:
            raise WorkspaceNotFoundError("Invalid Project ID.")
        if str(project.workspace_id) != str(workspace.id):
            raise WorkspaceValidationError("Project does not belong to this organization.")
        return project

    def create_tracked_entry(
        self,
        *,
        workspace: Any,
        team: Any,
        project: Any | None,
        task: Any | None,
        user: Any,
        now: datetime,
    ) -> Any:
        from infrastructure.persistence.project.models import ProjectEntry

        return ProjectEntry.objects.create(
            workspace=workspace,
            team=team,
            project=project,
            task=task,
            minutes=0,
            created_by=user,
            is_tracked=True,
            created_at=now,
        )

    def total_tracked_minutes_for_task(self, *, task_id: Any, user: Any) -> int:
        if task_id is None:
            return 0
        from infrastructure.persistence.project.models import ProjectEntry

        return (
            ProjectEntry.objects.filter(
                task_id=task_id,
                created_by=user,
                is_tracked=False,
            ).aggregate(total=Sum("minutes"))["total"]
            or 0
        )

    def find_active_entry(
        self,
        *,
        team_id: Any,
        user: Any,
        task_id: Any | None,
        project_id: Any | None,
    ) -> Any | None:
        from infrastructure.persistence.project.models import ProjectEntry

        qs = ProjectEntry.objects.filter(
            team_id=team_id,
            created_by=user,
            is_tracked=True,
        )
        if task_id:
            qs = qs.filter(task_id=task_id)
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs.order_by("-created_at").first()

    def stop_entry(self, *, entry: Any, tracked_minutes: int) -> None:
        entry.minutes = tracked_minutes
        entry.is_tracked = False
        entry.save(update_fields=["minutes", "is_tracked"])

    def delete_entry(self, *, entry: Any) -> Any | None:
        task_id = entry.task_id
        entry.delete()
        return task_id
