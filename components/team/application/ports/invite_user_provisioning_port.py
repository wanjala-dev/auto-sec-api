"""Port (team-owned): provision the user a persona invitation targets.

The team persona-invite flow needs a ``CustomUser``/``UserProfile`` provisioned,
but ``identity`` owns those models. This is the seam the team application layer
depends on; the adapter delegates to ``identity``'s application surface, which
performs the write (architecture-manifesto Rule 2 / architecture-skill C2). The
team context never imports ``users`` models.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class InvitedUserProbe:
    """Whether an account already exists for the email, and whether it is an
    established (usable-password) account."""

    exists: bool
    established: bool


@dataclass(frozen=True)
class ProvisionedUser:
    """The provisioned user's identity facts the invite flow still needs."""

    user_id: str
    email: str
    created: bool
    established: bool


class InviteUserProvisioningPort(abc.ABC):
    @abc.abstractmethod
    def probe(self, *, email: str) -> InvitedUserProbe: ...

    @abc.abstractmethod
    def provision_for_create(
        self,
        *,
        email: str,
        seed_is_contributor: bool,
        display_name: str,
        photo_url: str,
    ) -> ProvisionedUser:
        """Get-or-create the placeholder/established user for the create-invite
        flow (fill blank name from ``display_name``, set profile photo when
        blank)."""
        ...

    @abc.abstractmethod
    def provision_for_accept(
        self,
        *,
        email: str,
        seed_is_contributor: bool,
        password: str,
        first_name: str | None,
        last_name: str | None,
        active_workspace_id: str,
        active_team_id: str | None,
    ) -> ProvisionedUser:
        """Get-or-create + activate the user for the accept-invite flow (set
        password when supplied, force active/verified/onboard, park active
        workspace/team on the profile). ``is_contributor`` promotion is a
        separate step (:meth:`promote_contributor`)."""
        ...

    @abc.abstractmethod
    def promote_contributor(self, *, user_id: str) -> None:
        """Set ``is_contributor=True`` if not already set (idempotent). The
        accept flow calls this only after deciding a NEW contributor membership
        is being attached — preserving the original promotion guard."""
        ...
