"""Domain entity for an Invitation."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from components.team.domain.enums import InvitationStatus


@dataclass(frozen=True)
class InvitationEntity:
    """
    Domain entity for an invitation.

    An invitation is a pending or accepted request for a user (by e-mail)
    to join a specific team within a workspace.
    """

    id: int
    workspace_id: UUID
    team_id: int
    email: str
    code: str
    status: str
    date_sent: datetime.datetime
    accepted_at: datetime.datetime | None = None

    def __post_init__(self) -> None:
        if not self.email:
            raise ValueError("InvitationEntity.email is required.")

    @property
    def is_pending(self) -> bool:
        return self.status == InvitationStatus.INVITED

    @property
    def is_accepted(self) -> bool:
        return self.status == InvitationStatus.ACCEPTED
