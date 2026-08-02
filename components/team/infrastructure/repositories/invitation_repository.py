"""Adapter: read/write the team's own ``Invitation`` rows against the ORM.

Implements :class:`InvitationStorePort`. ``Invitation`` belongs to the ``team``
context, so this is an own-context repository — the ORM confined here keeps the
invite use cases ORM-free (architecture-manifesto Rule 2). Reads project the row
into a framework-free :class:`InvitationRecord` so the application layer never
holds an ORM instance.
"""

from __future__ import annotations

from datetime import datetime

from components.team.application.ports.invitation_store_port import (
    InvitationRecord,
    InvitationStorePort,
)


class OrmInvitationRepository(InvitationStorePort):
    @staticmethod
    def _to_record(invitation) -> InvitationRecord:
        return InvitationRecord(
            id=str(invitation.id),
            email=invitation.email,
            token=invitation.token,
            persona=invitation.persona,
            role=invitation.role,
            status=invitation.status,
            workspace_id=str(invitation.workspace_id),
            team_id=str(invitation.team_id) if invitation.team_id else None,
            invited_by_id=str(invitation.invited_by_id) if invitation.invited_by_id else None,
            expires_at=invitation.expires_at,
            permission_group_ids=list(getattr(invitation, "permission_group_ids", []) or []),
        )

    def create(
        self,
        *,
        workspace_id: str,
        team_id: str | None,
        email: str,
        code: str,
        token: str,
        persona: str,
        role: str,
        invited_by_id: str | None,
        expires_at: datetime,
        permission_group_ids: list[str],
    ) -> InvitationRecord:
        from infrastructure.persistence.team.models import Invitation

        invitation = Invitation.objects.create(
            workspace_id=workspace_id,
            team_id=team_id,
            email=email,
            code=code,
            token=token,
            persona=persona,
            role=role,
            invited_by_id=invited_by_id,
            expires_at=expires_at,
            status=Invitation.INVITED,
            permission_group_ids=permission_group_ids,
        )
        return self._to_record(invitation)

    def find_by_token(self, *, token: str) -> InvitationRecord | None:
        from infrastructure.persistence.team.models import Invitation

        invitation = Invitation.objects.select_related("workspace", "team").filter(token=token).first()
        if invitation is None:
            return None
        return self._to_record(invitation)

    def mark_expired(self, *, invitation_id: str) -> None:
        from infrastructure.persistence.team.models import Invitation

        Invitation.objects.filter(id=invitation_id).update(status=Invitation.EXPIRED)

    def mark_accepted(self, *, invitation_id: str, accepted_at: datetime) -> None:
        from infrastructure.persistence.team.models import Invitation

        Invitation.objects.filter(id=invitation_id).update(status=Invitation.ACCEPTED, accepted_at=accepted_at)
