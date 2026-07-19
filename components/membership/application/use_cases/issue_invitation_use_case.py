"""Use case: issue a single invitation to an existing user.

Extracted from ``components.team.application.use_cases.issue_team_invitation_use_case``.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.membership.domain.errors import InvitationValidationError
from components.membership.application.ports.invitation_port import TeamInvitationPort


@dataclass(frozen=True)
class InvitationIssueResult:
    status: str
    email: str
    invitation: object | None = None
    invitee: object | None = None
    reason: str | None = None


class IssueInvitationUseCase:
    def __init__(self, *, invitation_store: TeamInvitationPort) -> None:
        self.invitation_store = invitation_store

    def execute(
        self,
        *,
        workspace,
        team,
        invitee,
        email: str,
        actor_id,
    ) -> InvitationIssueResult:
        normalized_email = (email or "").strip().lower()
        if not normalized_email:
            raise InvitationValidationError("Invitee email is required.")

        result = self.invitation_store.issue_invitation(
            workspace=workspace,
            team=team,
            invitee=invitee,
            email=normalized_email,
            actor_id=actor_id,
        )
        return InvitationIssueResult(
            status=result["status"],
            email=result["email"],
            invitation=result.get("invitation"),
            invitee=result.get("invitee"),
            reason=result.get("reason"),
        )
