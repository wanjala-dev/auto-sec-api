"""Use case: write the invited user's workspace membership + group rows.

The ``workspace`` context owns ``WorkspaceMembership`` / ``WorkspaceRole`` /
``WorkspaceGroup*``, so it owns this write. The team persona-invite accept flow
delegates here (through a team-owned port + adapter) rather than writing those
models from the team application layer (architecture-manifesto Rule 2 /
architecture-skill C2).

The write runs inside the caller's ``atomic()`` — this use case opens no
transaction of its own.

No Django imports — depends only on ports + DTOs.
"""

from __future__ import annotations

from components.workspace.application.commands.invite_membership_write import (
    ExistingMembershipProbe,
    WriteInviteMembershipCommand,
)
from components.workspace.application.ports.invite_membership_store_port import (
    InviteMembershipStorePort,
)


class WriteInviteMembershipUseCase:
    def __init__(self, *, store: InviteMembershipStorePort) -> None:
        self._store = store

    def probe_existing_membership(self, *, workspace_id: str, user_id: str) -> ExistingMembershipProbe:
        return self._store.probe_existing_membership(workspace_id=workspace_id, user_id=user_id)

    def execute(self, *, command: WriteInviteMembershipCommand) -> None:
        self._store.write_membership(command=command)
