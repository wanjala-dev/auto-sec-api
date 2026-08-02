"""DTOs for invited-user provisioning (identity-owned user write).

These frozen dataclasses carry exactly the facts a caller (the team persona
invite flow) hands to ``identity`` so ``identity`` can own the ``CustomUser`` /
``UserProfile`` write. They mirror, field-for-field, the data the two team
invite use cases used to write inline — so the behaviour is unchanged; only the
ownership of the write moves to the context that owns the model.

No Django imports.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EstablishedUserProbe:
    """Result of the up-front "is this an established account?" read.

    ``exists`` is True when *any* user row exists for the email; ``established``
    is True only when that user also has a *usable* password (i.e. can log in).
    """

    exists: bool
    established: bool


@dataclass(frozen=True)
class ProvisionInvitedUserCommand:
    """Facts needed to get-or-create + update the invited user.

    ``purpose`` selects the write shape, mirroring the two original call sites:

    - ``"create"`` — the create-invite flow: get-or-create a placeholder
      (unusable password when brand-new), fill blank names from ``display_name``,
      set the profile ``photo_url`` when blank. No password, no active-workspace
      parking, no membership-driven ``is_contributor`` promotion.
    - ``"accept"`` — the accept-invite flow: get-or-create, optionally set the
      chosen password, force ``is_active/is_verified/is_onboard_complete=True``,
      conditionally promote ``is_contributor``, fill blank first/last name, and
      park ``active_workspace_id`` (+ optional ``active_team_id``) on the profile.
    """

    purpose: str  # "create" | "accept"
    email: str
    seed_is_contributor: bool

    # create-flow inputs
    display_name: str = ""
    photo_url: str = ""

    # accept-flow inputs
    password: str = ""
    first_name: str | None = None
    last_name: str | None = None
    active_workspace_id: str | None = None
    active_team_id: str | None = None


@dataclass(frozen=True)
class ProvisionedInvitedUser:
    """The provisioned user's identity facts the caller still needs.

    ``created`` reflects whether the get-or-create actually created the row.
    ``established`` mirrors the accept-flow's "existing established user" signal
    at the moment of the write (used only by the create flow's return payload).
    """

    user_id: str
    email: str
    created: bool
    established: bool
