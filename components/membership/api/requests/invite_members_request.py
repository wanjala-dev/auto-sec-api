"""Input DTO for batch member invitations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InviteMembersRequest:
    """Input DTO for POST /membership/invitations/ endpoint."""

    workspace: str | int
    team: str | int
    email: str | None = None
    emails: list[str] | None = None
    user_ids: list[str | int] | None = None
