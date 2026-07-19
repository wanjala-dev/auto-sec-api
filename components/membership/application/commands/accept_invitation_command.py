"""Command for invitation acceptance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptInvitationCommand:
    """Command to accept a team invitation.

    Attributes:
        code: The invitation code to accept.
        actor: The authenticated user accepting the invitation.
    """

    code: str
    actor: object  # User instance
