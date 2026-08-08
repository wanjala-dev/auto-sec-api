"""Port: revoke a user's membership of a workspace.

The ``membership`` context owns ``WorkspaceMembership``, so it owns this write.
The port keeps the use case framework-free: the ORM flip, the audit row, and
the notification fan-out all live behind this interface in the repository.

Revocation is a SOFT state change, never a row delete — it reuses the existing
membership status machine (``Status.SUSPENDED``), which
``workspace_relationship_repository`` already treats as "revoked, reactivate on
re-join". Nothing is destroyed, so re-inviting the person restores them.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoveWorkspaceMemberCommand:
    """Who is being removed from where, and by whom."""

    workspace_id: str
    target_user_id: str
    performed_by: str
    # True when the actor is removing THEMSELVES ("leave workspace") — the use
    # case authorises that without ``manage_users`` (you may always leave).
    is_self_removal: bool = False
    reason: str = ""


@dataclass(frozen=True)
class RemoveWorkspaceMemberResult:
    """``removed`` is False when the call was an idempotent no-op (the
    membership was already revoked). ``already_revoked`` distinguishes that
    from "nothing to do because the row is gone" — the latter raises."""

    workspace_id: str
    target_user_id: str
    removed: bool
    already_revoked: bool = False


class WorkspaceMemberRemovalPort(abc.ABC):
    """Secondary port: revoke a membership + record the side effects."""

    @abc.abstractmethod
    def find_membership_role(self, *, workspace_id: str, user_id: str) -> str | None:
        """Return the target's membership role, or ``None`` when they are not a
        member of the workspace at all (→ 404 at the edge)."""

    @abc.abstractmethod
    def is_workspace_owner(self, *, workspace_id: str, user_id: str) -> bool:
        """True when *user_id* owns the workspace. Ownership is structural —
        an owner is never removable through this path."""

    @abc.abstractmethod
    def revoke(self, *, command: RemoveWorkspaceMemberCommand) -> RemoveWorkspaceMemberResult:
        """Flip the membership to the revoked state, write the audit row, and
        notify the removed user.

        Idempotent: an already-revoked membership returns
        ``removed=False, already_revoked=True`` without re-auditing or
        re-notifying.
        """
