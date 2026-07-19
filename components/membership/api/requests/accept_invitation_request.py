"""Input DTO for accepting invitations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptInvitationRequest:
    """Input DTO for POST /membership/invitations/accept/ endpoint."""

    code: str
