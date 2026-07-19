"""Input DTO for team creation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateTeamRequest:
    """Input DTO for POST /api/teams/ endpoint (TeamAddView.post).

    Used to create a new team within a workspace.
    """
    title: str
    workspace: str | int
    plan: str | int | None = None
