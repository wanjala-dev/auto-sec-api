"""ORM adapter for project creation.

Extracted from project_controller.py ProjectsView.post.
"""

from __future__ import annotations

from components.project.application.ports.create_project_port import (
    CreateProjectCommand,
    CreateProjectPort,
    CreateProjectResult,
)
from components.project.domain.errors import (
    TaskValidationError,
    TeamMembershipRequiredError,
    TeamNotFoundError,
)


class OrmCreateProjectRepository(CreateProjectPort):
    def create_project(self, *, command: CreateProjectCommand) -> CreateProjectResult:
        from infrastructure.persistence.project.models import Project
        from infrastructure.persistence.team.models import Team
        from infrastructure.persistence.users.models import CustomUser

        # ── Resolve team ────────────────────────────────────────────
        team = (
            Team.objects.select_related("workspace", "plan")
            .filter(
                pk=command.team_id,
                status=Team.ACTIVE,
            )
            .first()
        )
        if not team:
            raise TeamNotFoundError("Team not found or not active.")

        # ── Membership check ────────────────────────────────────────
        # Workspace admins/owners bypass team-membership (ADR 0002).
        user = CustomUser.objects.filter(id=command.user_id).first()
        if not user:
            raise TeamMembershipRequiredError("User not found.")
        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_admin_or_owner,
        )

        if not user_is_workspace_admin_or_owner(user, team.workspace):
            if not team.members.filter(id=user.id).exists():
                raise TeamMembershipRequiredError("You must be a member of this team.")

        # ── Workspace cross-check ───────────────────────────────────
        if command.workspace_id and str(command.workspace_id) != str(team.workspace_id):
            raise TaskValidationError("Workspace does not match the selected team.")

        # ── Create project ──────────────────────────────────────────
        workspace = team.workspace
        project = Project.objects.create(
            workspace=workspace,
            team=team,
            title=command.title,
            created_by=user,
        )

        return CreateProjectResult(success=True, project=project)
