"""Port: provision (get-or-create) the user an invitation targets.

The ``identity`` context owns ``CustomUser`` / ``UserProfile``. When the team
context accepts or creates a persona invitation it needs a user row provisioned
(placeholder-or-established, password/flags/name set, active workspace parked on
the profile). That write belongs to ``identity`` — so ``identity`` owns it behind
this port; the ORM adapter implements it.

No Django imports — depends only on the standard library + this context's DTOs.
"""

from __future__ import annotations

import abc

from components.identity.application.commands.invited_user_provisioning import (
    EstablishedUserProbe,
    ProvisionedInvitedUser,
    ProvisionInvitedUserCommand,
)


class InvitedUserStorePort(abc.ABC):
    """Secondary/driven port for invited-user provisioning writes + probes."""

    @abc.abstractmethod
    def probe_established_user(self, *, email: str) -> EstablishedUserProbe:
        """Read whether a user with a *usable* password already exists for
        ``email`` (drives the "existing user" branch) — no write."""
        ...

    @abc.abstractmethod
    def provision_invited_user(self, *, command: ProvisionInvitedUserCommand) -> ProvisionedInvitedUser:
        """Get-or-create the user for ``command.email`` and apply the invited
        flags/password/name + park the active workspace/team on the profile,
        exactly mirroring the previous in-line writes. Runs inside the caller's
        transaction (opens no competing ``atomic()``)."""
        ...

    @abc.abstractmethod
    def promote_contributor(self, *, user_id: str) -> None:
        """Set ``is_contributor=True`` if not already set. Idempotent; called
        by the accept flow only after the membership-preserve decision, so the
        original promotion guard (``not preserving and not already contributor``)
        is honoured by the caller."""
        ...
