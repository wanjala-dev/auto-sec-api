"""Command and result value objects for team creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateTeamCommand:
    """Command to create a new team.

    Attributes:
        title: The name of the team.
        workspace_id: The workspace where the team will be created.
        actor: The authenticated user performing the action.

    The team's billing plan is derived from the workspace server-side —
    it is intentionally NOT part of the command (client input must not
    dictate plan limits).
    """

    title: str
    workspace_id: object  # UUID
    actor: object  # User instance
