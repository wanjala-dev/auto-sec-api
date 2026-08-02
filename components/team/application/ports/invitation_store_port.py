"""Port (team-owned): read/write the team's own ``Invitation`` rows.

``Invitation`` (and ``Team``) belong to the ``team`` context, so these reads and
writes are own-context — extracting them behind a port keeps the invite use
cases ORM-free (architecture-manifesto Rule 2), with the ORM confined to the
repository adapter.

The DTO deliberately carries only the fields the use cases read, so the
application layer never holds an ORM instance.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class InvitationRecord:
    """Framework-free snapshot of an ``Invitation`` row."""

    id: str
    email: str
    token: str
    persona: str
    role: str
    status: str
    workspace_id: str
    team_id: str | None
    invited_by_id: str | None
    expires_at: datetime | None
    permission_group_ids: list[str] = field(default_factory=list)


class InvitationStorePort(abc.ABC):
    # Status constants mirrored from the ORM model so the application layer
    # compares against names, not the ORM class.
    STATUS_INVITED = "invited"
    STATUS_ACCEPTED = "accepted"
    STATUS_EXPIRED = "expired"

    @abc.abstractmethod
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
    ) -> InvitationRecord: ...

    @abc.abstractmethod
    def find_by_token(self, *, token: str) -> InvitationRecord | None: ...

    @abc.abstractmethod
    def mark_expired(self, *, invitation_id: str) -> None: ...

    @abc.abstractmethod
    def mark_accepted(self, *, invitation_id: str, accepted_at: datetime) -> None: ...
