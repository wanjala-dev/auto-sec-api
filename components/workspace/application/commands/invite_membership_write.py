"""DTOs for the invite-driven workspace membership write (workspace-owned).

The ``workspace`` context owns ``WorkspaceMembership`` / ``WorkspaceRole`` /
``WorkspaceGroup*``. These frozen dataclasses carry exactly the facts the team
persona-invite accept flow hands to ``workspace`` so ``workspace`` can own that
write. They mirror, field-for-field, the rows the team accept use case wrote
inline — behaviour is unchanged; only the ownership of the write moves.

No Django imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExistingMembershipProbe:
    """Result of the up-front membership read that decides whether the accept
    preserves an existing active membership (no role/persona clobber)."""

    exists: bool
    active: bool


@dataclass(frozen=True)
class WriteInviteMembershipCommand:
    """Facts needed to write the invited user's membership + group rows.

    ``preserving_existing_membership`` short-circuits to "refresh accepted_at
    only" — mirroring the original guard that stops an existing owner/admin
    being downgraded by accepting a stray invite.
    """

    workspace_id: str
    user_id: str
    persona: str
    role: str
    invited_by_id: str | None
    accepted_at: datetime
    preserving_existing_membership: bool
    permission_group_ids: list[str] = field(default_factory=list)
