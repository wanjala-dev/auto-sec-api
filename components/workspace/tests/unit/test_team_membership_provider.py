from __future__ import annotations

from components.team.application.providers.team_membership_provider import (
    TeamMembershipProvider,
)
from components.workspace.application.service import (
    WorkspaceService,
)
from components.team.infrastructure.repositories.team_membership_repository import (
    OrmTeamMembershipRepository,
)


def test_team_membership_provider_builds_service():
    service = TeamMembershipProvider().build_service()

    assert isinstance(service, WorkspaceService)


def test_team_membership_provider_builds_store():
    store = TeamMembershipProvider().build_store()

    assert isinstance(store, OrmTeamMembershipRepository)
