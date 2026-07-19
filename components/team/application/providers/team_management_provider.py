from __future__ import annotations

from components.team.application.use_cases.create_team_use_case import (
    CreateTeamUseCase,
)
from components.team.application.use_cases.update_team_use_case import (
    UpdateTeamUseCase,
)
from components.team.infrastructure.repositories.team_management_repository import (
    OrmTeamManagementRepository,
)


class TeamManagementProvider:
    def build_create_team_use_case(self) -> CreateTeamUseCase:
        return CreateTeamUseCase(
            team_management_store=OrmTeamManagementRepository(),
        )

    def build_update_team_use_case(self) -> UpdateTeamUseCase:
        return UpdateTeamUseCase(
            team_management_store=OrmTeamManagementRepository(),
        )
