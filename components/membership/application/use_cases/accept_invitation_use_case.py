"""Use case: accept a team invitation.

Extracted from ``components.team.application.use_cases.accept_team_invitation_use_case``.
"""

from __future__ import annotations

from components.membership.domain.errors import (
    InvitationValidationError,
    MembershipAuthorizationError,
)
from components.membership.application.ports.invitation_port import TeamInvitationPort


class AcceptInvitationUseCase:
    def __init__(self, *, invitation_store: TeamInvitationPort) -> None:
        self.invitation_store = invitation_store

    def execute(self, *, code: str, actor):
        normalized_code = (code or "").strip()
        if not normalized_code:
            raise InvitationValidationError("Invite code is required.")
        if not actor or not getattr(actor, "is_authenticated", False):
            raise MembershipAuthorizationError("Authentication required.")
        return self.invitation_store.accept_invitation(
            code=normalized_code,
            actor=actor,
        )
