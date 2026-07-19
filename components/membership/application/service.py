"""Application service for the membership bounded context.

Orchestration only — delegates to use cases for business logic.
This is the single orchestration entry point for membership operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.membership.application.commands import (
    AcceptInvitationCommand,
    ProcessInvitationBatchCommand,
)
from components.membership.application.providers.membership_provider import (
    MembershipProvider,
)


@dataclass
class MembershipService:
    """Application service for membership operations.

    Covers invitation lifecycle, member queries, and access control.
    """

    provider: MembershipProvider = field(default_factory=MembershipProvider)

    def accept_invitation(self, command: AcceptInvitationCommand):
        """Orchestrate invitation acceptance."""
        use_case = self.provider.build_accept_invitation_use_case()
        return use_case.execute(
            code=command.code,
            actor=command.actor,
        )

    def process_invitation_batch(self, command: ProcessInvitationBatchCommand):
        """Orchestrate batch invitation processing."""
        use_case = self.provider.build_process_invitation_batch_use_case()
        return use_case.execute(
            actor=command.actor,
            workspace_id=command.workspace_id,
            team_id=command.team_id,
            emails=command.emails,
            user_ids=command.user_ids,
            request=command.request,
            is_staff=command.is_staff,
            is_superuser=command.is_superuser,
        )

    def invitation_notification(self, invitation, actor):
        """Orchestrate invitation notification handling."""
        use_case = self.provider.build_notification_use_case()
        return use_case.handle_invitation_accepted(
            invitation=invitation,
            actor=actor,
        )

    def query_membership(self):
        """Access membership query service for read queries."""
        return self.provider.build_query_service()
