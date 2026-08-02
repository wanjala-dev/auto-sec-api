"""Port (team-owned): write the invited user's workspace membership rows.

The team persona-invite accept flow needs a ``WorkspaceMembership`` (+ role +
group) row written, but ``workspace`` owns those models. This is the seam the
team application layer depends on; the adapter delegates to ``workspace``'s
application surface, which performs the write (architecture-manifesto Rule 2 /
architecture-skill C2). The team context never imports ``workspaces`` models.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MembershipProbe:
    """Whether the user already has a membership in the workspace and whether it
    is ACTIVE (drives the preserve-existing-role guard)."""

    exists: bool
    active: bool


class WorkspaceMembershipWritePort(abc.ABC):
    @abc.abstractmethod
    def probe_membership(self, *, workspace_id: str, user_id: str) -> MembershipProbe: ...

    @abc.abstractmethod
    def write_membership(
        self,
        *,
        workspace_id: str,
        user_id: str,
        persona: str,
        role: str,
        invited_by_id: str | None,
        accepted_at: datetime,
        preserving_existing_membership: bool,
        permission_group_ids: list[str] | None = None,
    ) -> None:
        """Write the persona/role membership row (or just refresh accepted_at
        when preserving an existing active membership) and enroll into the
        selected permission groups. Runs inside the caller's ``atomic()``."""
        ...
