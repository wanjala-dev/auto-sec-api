"""Command and result value objects for team updates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateTeamCommand:
    """Command to update an existing team.

    Attributes:
        actor: The authenticated user performing the action.
        validated_data: Dictionary of validated field updates for the team.
        is_staff: Whether the actor is a staff member.
        is_superuser: Whether the actor is a superuser.
    """

    actor: object  # User instance
    validated_data: dict
    is_staff: bool = False
    is_superuser: bool = False
