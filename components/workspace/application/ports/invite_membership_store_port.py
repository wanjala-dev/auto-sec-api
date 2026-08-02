"""Port: write the invited user's workspace membership + group rows.

The ``workspace`` context owns ``WorkspaceMembership`` / ``WorkspaceRole`` /
``WorkspaceGroup*``. The team persona-invite accept flow delegates the membership
write here (through a team-owned port + adapter) instead of writing those models
from the team application layer (architecture-manifesto Rule 2 / architecture
skill C2). The ORM adapter implements this; the write runs inside the caller's
transaction.

No Django imports.
"""

from __future__ import annotations

import abc

from components.workspace.application.commands.invite_membership_write import (
    ExistingMembershipProbe,
    WriteInviteMembershipCommand,
)


class InviteMembershipStorePort(abc.ABC):
    """Secondary/driven port for invite-driven membership writes + the probe."""

    @abc.abstractmethod
    def probe_existing_membership(self, *, workspace_id: str, user_id: str) -> ExistingMembershipProbe:
        """Read whether the user already has a membership in the workspace and
        whether it is ACTIVE (drives the "preserve existing role" guard) — no
        write."""
        ...

    @abc.abstractmethod
    def write_membership(self, *, command: WriteInviteMembershipCommand) -> None:
        """Write the persona/role membership row (or just refresh ``accepted_at``
        when preserving an existing active membership) and enroll the user into
        the selected permission groups. Runs inside the caller's ``atomic()``."""
        ...
