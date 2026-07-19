"""Input DTO for accepting team invitations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptInvitationRequest:
    """Input DTO for POST /api/teams/invite/accept/ endpoint (AcceptInvitationView.post).

    Used to accept a pending team invitation.
    """
    code: str
