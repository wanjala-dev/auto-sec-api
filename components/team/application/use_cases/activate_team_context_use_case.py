from __future__ import annotations

from components.team.domain.errors import TeamValidationError
from components.team.application.ports.team_context_port import TeamContextPort


class ActivateTeamContextUseCase:
    def __init__(self, *, team_context_store: TeamContextPort) -> None:
        self.team_context_store = team_context_store

    def execute(
        self,
        *,
        team_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        if not team_id:
            raise TeamValidationError("team_id is required.")

        team = self.team_context_store.get_accessible_team(
            team_id=int(team_id),
            actor_id=actor_id,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        self.team_context_store.activate_team_for_user(actor_id=actor_id, team=team)
        return team
