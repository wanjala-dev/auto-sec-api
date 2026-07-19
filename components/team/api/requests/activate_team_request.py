"""Input DTO for team activation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivateTeamRequest:
    """Input DTO for POST /api/teams/activate/ endpoint (TeamActivateView.post).

    Used to activate a team as the user's active team context.
    """
    team_id: str | int
