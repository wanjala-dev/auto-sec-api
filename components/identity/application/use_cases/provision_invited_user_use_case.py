"""Use case: provision (get-or-create + update) the user an invitation targets.

The ``identity`` context owns ``CustomUser`` / ``UserProfile``, so it owns this
write. The team persona-invite flow delegates here (through a team-owned port +
adapter) instead of reaching into ``users`` ORM from the team application layer
— keeping the user write on the owning side of the boundary
(architecture-manifesto Rule 2 / architecture-skill C2).

The write runs inside the caller's ``atomic()`` — this use case opens no
transaction of its own, so a failure later in the invite flow rolls the user
write back with everything else.

No Django imports — depends only on ports + DTOs.
"""

from __future__ import annotations

from components.identity.application.commands.invited_user_provisioning import (
    EstablishedUserProbe,
    ProvisionedInvitedUser,
    ProvisionInvitedUserCommand,
)
from components.identity.application.ports.invited_user_store_port import (
    InvitedUserStorePort,
)


class ProvisionInvitedUserUseCase:
    def __init__(self, *, store: InvitedUserStorePort) -> None:
        self._store = store

    def probe_established_user(self, *, email: str) -> EstablishedUserProbe:
        return self._store.probe_established_user(email=email)

    def execute(self, *, command: ProvisionInvitedUserCommand) -> ProvisionedInvitedUser:
        return self._store.provision_invited_user(command=command)

    def promote_contributor(self, *, user_id: str) -> None:
        self._store.promote_contributor(user_id=user_id)
