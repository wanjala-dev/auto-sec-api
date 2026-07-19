"""Command and result value objects for team context activation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivateTeamContextCommand:
    """Command to activate a team as the current context.

    Attributes:
        team_id: The ID of the team to activate.
        actor_id: The ID of the authenticated user.
        is_staff: Whether the actor is a staff member.
        is_superuser: Whether the actor is a superuser.
    """

    team_id: object  # int
    actor_id: object  # UUID or int
    is_staff: bool = False
    is_superuser: bool = False
