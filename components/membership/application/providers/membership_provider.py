"""Composition root for the membership context.

Wires all ports to their ORM/adapter implementations.
"""

from __future__ import annotations

from components.membership.application.ports.invitation_port import InvitationPort
from components.membership.application.ports.membership_port import MembershipPort
from components.membership.application.ports.role_permissions_read_port import (
    RolePermissionsReadPort,
)
from components.membership.application.queries.membership_query import (
    MembershipQueryService,
)
from components.membership.application.use_cases.accept_invitation_use_case import (
    AcceptInvitationUseCase,
)
from components.membership.application.use_cases.establish_workspace_relationship_use_case import (
    EstablishWorkspaceRelationshipUseCase,
)
from components.membership.application.use_cases.invitation_notification_use_case import (
    InvitationNotificationUseCase,
)
from components.membership.application.use_cases.issue_invitation_use_case import (
    IssueInvitationUseCase,
)
from components.membership.application.use_cases.prepare_invitation_use_case import (
    PrepareInvitationUseCase,
)
from components.membership.application.use_cases.process_invitation_batch_use_case import (
    ProcessInvitationBatchUseCase,
)
from components.membership.application.use_cases.remove_workspace_member_use_case import (
    RemoveWorkspaceMemberUseCase,
)
from components.membership.infrastructure.adapters.invitation_notification_adapter import (
    InvitationNotificationAdapter,
)
from components.membership.infrastructure.adapters.invited_user_registration_adapter import (
    InvitedUserRegistrationAdapter,
)
from components.membership.infrastructure.repositories.invitation_repository import (
    OrmInvitationRepository,
)
from components.membership.infrastructure.repositories.membership_query_repository import (
    OrmMembershipQueryRepository,
)
from components.membership.infrastructure.repositories.membership_repository import (
    OrmMembershipRepository,
)
from components.membership.infrastructure.repositories.team_membership_repository import (
    OrmTeamMembershipRepository,
)
from components.membership.infrastructure.repositories.workspace_relationship_repository import (
    OrmWorkspaceRelationshipRepository,
)
from components.team.domain.policies.team_membership_policy_service import (
    TeamMembershipPolicyService,
)
from components.workspace.application.use_cases.register_invited_user_use_case import (
    RegisterInvitedUserUseCase,
)
from components.workspace.domain.policies.contributor_enrollment_policy_service import (
    ContributorEnrollmentPolicyService,
)


class MembershipProvider:
    """Factory for membership port instances and use cases."""

    # ── Access-control ports (original) ──────────────────────────────

    def build_membership_port(self) -> MembershipPort:
        return OrmMembershipRepository()

    def build_role_permissions_reader(self) -> RolePermissionsReadPort:
        """RBAC read-port for the membership permission resolver.

        Wires the ORM adapter that reads the ``workspaces`` RBAC tables
        (``WorkspaceRole`` / ``WorkspacePermissionGrant`` /
        ``WorkspaceGroupMembership``) so ``membership_has_permission`` stays
        ORM-free (architecture-manifesto Rule 2).
        """
        from components.membership.infrastructure.repositories.role_permissions_read_repository import (
            OrmRolePermissionsReadRepository,
        )

        return OrmRolePermissionsReadRepository()

    def build_invitation_port(self) -> InvitationPort:

        # Legacy port — kept for backward compatibility with existing consumers
        return OrmMembershipRepository()

    # ── Team membership store ────────────────────────────────────────

    def _build_team_membership_store(self) -> OrmTeamMembershipRepository:
        return OrmTeamMembershipRepository(
            team_membership_policy=TeamMembershipPolicyService(),
            contributor_enrollment_policy=ContributorEnrollmentPolicyService(),
        )

    # ── Invitation store ─────────────────────────────────────────────

    def _build_invitation_store(self) -> OrmInvitationRepository:
        return OrmInvitationRepository(
            team_membership_store=self._build_team_membership_store(),
        )

    # ── Invitation use cases ─────────────────────────────────────────

    def build_accept_invitation_use_case(self) -> AcceptInvitationUseCase:
        return AcceptInvitationUseCase(
            invitation_store=self._build_invitation_store(),
        )

    def build_issue_invitation_use_case(self) -> IssueInvitationUseCase:
        return IssueInvitationUseCase(
            invitation_store=self._build_invitation_store(),
        )

    def build_prepare_invitation_use_case(self) -> PrepareInvitationUseCase:
        return PrepareInvitationUseCase(
            invitation_store=self._build_invitation_store(),
        )

    def build_notification_use_case(self) -> InvitationNotificationUseCase:
        return InvitationNotificationUseCase(
            notification_port=InvitationNotificationAdapter(),
        )

    def build_register_invited_user_use_case(self) -> RegisterInvitedUserUseCase:
        return RegisterInvitedUserUseCase(
            invited_user_registration_port=InvitedUserRegistrationAdapter(),
        )

    def build_process_invitation_batch_use_case(self) -> ProcessInvitationBatchUseCase:
        return ProcessInvitationBatchUseCase(
            prepare_use_case=self.build_prepare_invitation_use_case(),
            issue_use_case=self.build_issue_invitation_use_case(),
            register_use_case=self.build_register_invited_user_use_case(),
            notification_use_case=self.build_notification_use_case(),
        )

    # ── Query service ────────────────────────────────────────────────

    def build_query_service(self) -> MembershipQueryService:
        return MembershipQueryService(
            membership_queries=OrmMembershipQueryRepository(),
        )

    # ── Self-service workspace relationship (onboarding "support an org") ──

    def build_establish_relationship_use_case(
        self,
    ) -> EstablishWorkspaceRelationshipUseCase:
        return EstablishWorkspaceRelationshipUseCase(
            port=OrmWorkspaceRelationshipRepository(),
        )

    # ── Member removal (revoke membership / leave workspace) ──────────

    def build_remove_workspace_member_use_case(self) -> RemoveWorkspaceMemberUseCase:
        from components.membership.infrastructure.repositories.workspace_member_removal_repository import (
            OrmWorkspaceMemberRemovalRepository,
        )

        return RemoveWorkspaceMemberUseCase(port=OrmWorkspaceMemberRemovalRepository())
