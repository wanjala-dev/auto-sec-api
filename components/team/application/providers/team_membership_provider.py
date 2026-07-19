from __future__ import annotations

from components.workspace.application.service import (
    WorkspaceService,
)
from components.workspace.domain.policies.contributor_enrollment_policy_service import (
    ContributorEnrollmentPolicyService,
)
from components.team.domain.policies.team_membership_policy_service import (
    TeamMembershipPolicyService,
)
from components.team.infrastructure.repositories.team_membership_repository import (
    OrmTeamMembershipRepository,
)


class TeamMembershipProvider:
    def build_store(self) -> OrmTeamMembershipRepository:
        return OrmTeamMembershipRepository(
            team_membership_policy=TeamMembershipPolicyService(),
            contributor_enrollment_policy=ContributorEnrollmentPolicyService(),
        )

    def build_service(self) -> WorkspaceService:
        return WorkspaceService(
            team_membership_store=self.build_store(),
        )
