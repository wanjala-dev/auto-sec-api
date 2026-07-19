from __future__ import annotations

from components.team.domain.errors import (
    TeamValidationError,
    WorkspaceAuthorizationError,
)
from components.team.application.ports.team_management_port import TeamManagementPort


class CreateTeamUseCase:
    """Create a team inside a workspace.

    The team's billing plan is DERIVED from the workspace server-side —
    never taken from the client. (Historically the controller accepted a
    client-supplied ``plan`` pk, which both let a client pick a
    higher-limit plan and made the Teams-index inline create 400 whenever
    the client context hadn't hydrated a plan yet.)
    """

    def __init__(self, *, team_management_store: TeamManagementPort) -> None:
        self.team_management_store = team_management_store

    def execute(
        self,
        *,
        title,
        workspace_id,
        actor,
    ):
        if not actor or not getattr(actor, "is_authenticated", False):
            raise WorkspaceAuthorizationError("Authentication required.")
        if not all([title, workspace_id]):
            raise TeamValidationError("Missing required fields.")

        return self.team_management_store.create_team(
            title=title,
            workspace_id=workspace_id,
            actor=actor,
        )
