"""Provider/composition root for the team persona-invite use cases.

Wires the team-owned ports to their adapters so the controller can build fully
composed ``CreateWorkspaceInviteUseCase`` / ``AcceptWorkspaceInviteUseCase``
instances without importing infrastructure. Lazy-imports the adapters so this
module stays infra-free at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    from components.team.application.use_cases.accept_workspace_invite_use_case import (
        AcceptWorkspaceInviteUseCase,
    )
    from components.team.application.use_cases.create_workspace_invite_use_case import (
        CreateWorkspaceInviteUseCase,
    )


class WorkspaceInviteProvider:
    """Driving-side façade building the two persona-invite use cases."""

    @staticmethod
    def _invitation_store():
        from components.team.infrastructure.repositories.invitation_repository import (
            OrmInvitationRepository,
        )

        return OrmInvitationRepository()

    @staticmethod
    def _user_provisioning():
        from components.team.infrastructure.adapters.identity_invite_user_provisioning_adapter import (
            IdentityInviteUserProvisioningAdapter,
        )

        return IdentityInviteUserProvisioningAdapter()

    @staticmethod
    def _membership_write():
        from components.team.infrastructure.adapters.workspace_membership_write_adapter import (
            WorkspaceMembershipWriteAdapter,
        )

        return WorkspaceMembershipWriteAdapter()

    @staticmethod
    def _invite_context():
        from components.team.infrastructure.adapters.workspace_invite_context_adapter import (
            WorkspaceInviteContextAdapter,
        )

        return WorkspaceInviteContextAdapter()

    @staticmethod
    def _notifier():
        from components.team.infrastructure.adapters.invite_notifier_adapter import (
            InviteNotifierAdapter,
        )

        return InviteNotifierAdapter()

    @staticmethod
    def _token():
        from components.team.infrastructure.adapters.invite_token_adapter import (
            SimpleJwtInviteTokenAdapter,
        )

        return SimpleJwtInviteTokenAdapter()

    @staticmethod
    def _team_enrollment():
        from components.team.infrastructure.adapters.invite_team_enrollment_adapter import (
            InviteTeamEnrollmentAdapter,
        )

        return InviteTeamEnrollmentAdapter()

    def build_create_use_case(self) -> CreateWorkspaceInviteUseCase:
        from components.team.application.use_cases.create_workspace_invite_use_case import (
            CreateWorkspaceInviteUseCase,
        )

        return CreateWorkspaceInviteUseCase(
            invitations=self._invitation_store(),
            user_provisioning=self._user_provisioning(),
            invite_context=self._invite_context(),
            notifier=self._notifier(),
        )

    def build_accept_use_case(self) -> AcceptWorkspaceInviteUseCase:
        from components.team.application.use_cases.accept_workspace_invite_use_case import (
            AcceptWorkspaceInviteUseCase,
        )

        return AcceptWorkspaceInviteUseCase(
            invitations=self._invitation_store(),
            user_provisioning=self._user_provisioning(),
            membership_write=self._membership_write(),
            tokens=self._token(),
            team_enrollment=self._team_enrollment(),
        )


_default = WorkspaceInviteProvider()


def get_workspace_invite_provider() -> WorkspaceInviteProvider:
    """Return the default provider — composition root for the persona-invite use
    cases. Override by monkeypatching ``_default`` in tests."""
    return _default
