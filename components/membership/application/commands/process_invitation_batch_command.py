"""Command for batch invitation processing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessInvitationBatchCommand:
    """Command to process a batch of team invitations.

    Attributes:
        actor: The authenticated user issuing the invitations.
        workspace_id: The workspace where invitations are issued.
        team_id: The team where users are being invited.
        emails: List of email addresses to invite.
        user_ids: List of existing user IDs to invite.
        request: The HTTP request object (optional, for notifications).
        is_staff: Whether the actor is a staff member.
        is_superuser: Whether the actor is a superuser.
    """

    actor: object  # User instance
    workspace_id: object  # UUID
    team_id: object  # int
    emails: list[str] | None = None
    user_ids: list | None = None
    request: object | None = None
    is_staff: bool = False
    is_superuser: bool = False
