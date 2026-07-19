"""Use case: prepare (validate) a batch of invitations.

Extracted from ``components.team.application.use_cases.prepare_team_invitation_use_case``.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.membership.domain.errors import MembershipAuthorizationError
from components.membership.application.ports.invitation_port import TeamInvitationPort


@dataclass(frozen=True)
class PreparedInvitationBatch:
    workspace: object
    team: object
    existing_users: list
    new_emails: list[str]
    missing_user_ids: list[str]


class PrepareInvitationUseCase:
    def __init__(self, *, invitation_store: TeamInvitationPort) -> None:
        self.invitation_store = invitation_store

    def execute(
        self,
        *,
        workspace_id,
        team_id,
        actor,
        emails: list[str] | None = None,
        user_ids: list | None = None,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> PreparedInvitationBatch:
        if not actor or not getattr(actor, "is_authenticated", False):
            raise MembershipAuthorizationError("Authentication required.")

        normalized_emails = self._normalize_emails(emails or [])
        batch = self.invitation_store.prepare_invitation_batch(
            workspace_id=workspace_id,
            team_id=team_id,
            actor=actor,
            normalized_emails=normalized_emails,
            user_ids=user_ids or [],
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

        return PreparedInvitationBatch(
            workspace=batch["workspace"],
            team=batch["team"],
            existing_users=batch["existing_users"],
            new_emails=batch["new_emails"],
            missing_user_ids=batch["missing_user_ids"],
        )

    @staticmethod
    def _normalize_emails(emails: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for value in emails:
            email = (value or "").strip().lower()
            if not email or email in seen:
                continue
            normalized.append(email)
            seen.add(email)
        return normalized
