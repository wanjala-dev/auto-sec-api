"""ORM adapter for column query operations.

Extracted from ColumnsView.get() in project_controller.py.
"""

from __future__ import annotations

from typing import Any

from components.workspace.application.ports.column_query_port import (
    ColumnFilterRequest,
    ColumnQueryPort,
)
from components.workspace.domain.errors import (
    TeamMembershipRequiredError,
    WorkspaceMembershipRequiredError,
    WorkspaceNotFoundError,
    WorkspaceValidationError,
)


class OrmColumnQueryRepository(ColumnQueryPort):
    def fetch_columns(self, *, request: ColumnFilterRequest) -> list[Any]:
        from infrastructure.persistence.project.models import Column

        user_assigned = request.user_assigned
        user = request.user

        if user_assigned and user:
            return self._fetch_user_assigned_columns(request)

        if request.project_id and request.team_id and request.workspace_id:
            team, workspace = self._validate_team_workspace(request.team_id, request.workspace_id)
            self._check_team_membership(user, team)
            project = self._get_project(request.project_id, team, workspace)
            return self._prefetch(Column.objects.filter(project=project, team=team, workspace=workspace))

        if request.team_id and request.workspace_id:
            team, workspace = self._validate_team_workspace(request.team_id, request.workspace_id)
            self._check_team_membership(user, team)
            # A team's *default* board is the columns NOT bound to any project.
            # Project-scoped columns belong to that project's own board and must
            # not bleed into the team board (fetched via the project+team branch
            # above). Without project__isnull the team board mixes both.
            return self._prefetch(Column.objects.filter(team=team, workspace=workspace, project__isnull=True))

        if request.team_id:
            team = self._get_team(request.team_id)
            self._check_team_membership(user, team)
            return self._prefetch(Column.objects.filter(team=team, project__isnull=True))

        if request.workspace_id:
            workspace = self._get_workspace(request.workspace_id)
            self._check_workspace_membership(user, workspace)
            return self._prefetch(Column.objects.filter(workspace=workspace))

        if request.column_id:
            column = self._get_column(request.column_id)
            self._check_workspace_membership(user, column.workspace)
            return [column]

        raise WorkspaceValidationError("Column, Project, Team, or Workspace ID is required.")

    def _fetch_user_assigned_columns(self, request: ColumnFilterRequest) -> list[Any]:
        from infrastructure.persistence.project.models import Column

        user = request.user

        if request.project_id and request.team_id and request.workspace_id:
            team, workspace = self._validate_team_workspace(request.team_id, request.workspace_id)
            self._check_team_membership(user, team)
            project = self._get_project(request.project_id, team, workspace)
            return self._prefetch(
                Column.objects.filter(
                    project=project,
                    team=team,
                    workspace=workspace,
                    is_deleted=False,
                    tasks__created_by=user,
                ).distinct()
            )

        if request.team_id and request.workspace_id:
            team, workspace = self._validate_team_workspace(request.team_id, request.workspace_id)
            self._check_team_membership(user, team)
            return self._prefetch(
                Column.objects.filter(
                    team=team,
                    workspace=workspace,
                    is_deleted=False,
                    tasks__created_by=user,
                ).distinct()
            )

        if request.team_id:
            team = self._get_team(request.team_id)
            self._check_team_membership(user, team)
            return self._prefetch(
                Column.objects.filter(
                    team=team,
                    is_deleted=False,
                    tasks__created_by=user,
                ).distinct()
            )

        if request.workspace_id:
            workspace = self._get_workspace(request.workspace_id)
            self._check_workspace_membership(user, workspace)
            return self._prefetch(
                Column.objects.filter(
                    workspace=workspace,
                    is_deleted=False,
                    tasks__created_by=user,
                ).distinct()
            )

        raise WorkspaceValidationError("Project, Team, or Workspace ID is required when filtering by user.")

    # -- helpers --

    @staticmethod
    def _prefetch(qs) -> list[Any]:
        return list(qs.prefetch_related("tasks"))

    @staticmethod
    def _get_team(team_id: Any) -> Any:
        from infrastructure.persistence.team.models import Team

        try:
            return Team.objects.select_related("workspace").get(pk=team_id, status=Team.ACTIVE)
        except Team.DoesNotExist:
            raise WorkspaceNotFoundError("Team not found.")

    @staticmethod
    def _get_workspace(workspace_id: Any) -> Any:
        from infrastructure.persistence.workspaces.models import Workspace

        try:
            return Workspace.objects.get(pk=workspace_id)
        except Workspace.DoesNotExist:
            raise WorkspaceNotFoundError("Workspace not found.")

    @staticmethod
    def _get_column(column_id: Any) -> Any:
        from infrastructure.persistence.project.models import Column

        try:
            return Column.objects.select_related("workspace").get(pk=column_id)
        except Column.DoesNotExist:
            raise WorkspaceNotFoundError("Column not found.")

    @staticmethod
    def _get_project(project_id: Any, team: Any, workspace: Any) -> Any:
        from infrastructure.persistence.project.models import Project

        try:
            return Project.objects.get(pk=project_id, team=team, workspace=workspace)
        except Project.DoesNotExist:
            raise WorkspaceNotFoundError("Project not found.")

    def _validate_team_workspace(self, team_id: Any, workspace_id: Any) -> tuple[Any, Any]:
        team = self._get_team(team_id)
        workspace = self._get_workspace(workspace_id)
        if str(team.workspace_id) != str(workspace.id):
            # Team belongs to a different workspace — return empty rather than
            # error.  The frontend may hold a stale team_id when the user
            # switches workspaces; an error here surfaces as a confusing alert.
            raise WorkspaceNotFoundError("Team does not belong to this workspace.")
        return team, workspace

    @staticmethod
    def _check_team_membership(user: Any, team: Any) -> None:
        # Workspace admins/owners bypass team-membership for every team in
        # their workspace (including the Agents team — AI-only members but
        # admins must be able to see AI findings). Per ADR 0002 this reads
        # ``WorkspaceMembership.role``, never persona.
        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_admin_or_owner,
        )

        if user_is_workspace_admin_or_owner(user, team.workspace):
            return
        if not team.members.filter(id=user.id).exists():
            raise TeamMembershipRequiredError("You must be a member of this team.")

    @staticmethod
    def _check_workspace_membership(user: Any, workspace: Any) -> None:
        from components.workspace.application.facades.workspace_facade import user_is_workspace_member

        if not user_is_workspace_member(user, workspace):
            raise WorkspaceMembershipRequiredError("You must belong to the organization to perform this action.")
