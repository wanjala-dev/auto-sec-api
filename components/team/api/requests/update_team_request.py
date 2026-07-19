"""Input DTO for team updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UpdateTeamRequest:
    """Input DTO for PATCH /api/teams/<uuid>/ endpoint (TeamAddByUuidView.patch).

    Used to partially update team properties.
    """
    uuid: str | None = None
    title: str | None = None
    kind: str | None = None
    privacy: str | None = None
    status: str | None = None
    plan: str | int | None = None
    members: list[str | int] | None = None
    extra_data: dict[str, Any] | None = None
