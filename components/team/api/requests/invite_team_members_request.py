"""Input DTO for team member invitations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InviteTeamMembersRequest:
    """Input DTO for POST /api/teams/invite/ endpoint (InvitationView.post).

    Used to invite users to a team by email address or user ID.
    """
    workspace: str | int
    team: str | int
    email: str | None = None
    emails: list[str] | None = None
    user_ids: list[str | int] | None = None
