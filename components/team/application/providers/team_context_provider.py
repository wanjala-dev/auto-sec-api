from __future__ import annotations

from components.team.application.use_cases.activate_team_context_use_case import (
    ActivateTeamContextUseCase,
)
from components.team.infrastructure.repositories.team_context_repository import (
    OrmTeamContextRepository,
)


class TeamContextProvider:
    @staticmethod
    def build_team_context_port() -> OrmTeamContextRepository:
        """Return a team context port for read queries (resolve_active_team, etc.)."""
        return OrmTeamContextRepository()

    def build_activate_team_context_use_case(self) -> ActivateTeamContextUseCase:
        return ActivateTeamContextUseCase(
            team_context_store=OrmTeamContextRepository(),
        )
