from __future__ import annotations

from components.team.domain.errors import WorkspaceAuthorizationError
from components.team.application.ports.team_management_port import TeamManagementPort


class UpdateTeamUseCase:
    def __init__(self, *, team_management_store: TeamManagementPort) -> None:
        self.team_management_store = team_management_store

    def execute(
        self,
        *,
        actor,
        validated_data: dict,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        if not actor or not getattr(actor, "is_authenticated", False):
            raise WorkspaceAuthorizationError("Authentication required.")

        return self.team_management_store.update_active_team(
            actor=actor,
            validated_data=validated_data,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
