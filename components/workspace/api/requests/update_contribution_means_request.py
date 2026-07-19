"""Request DTO for contribution means update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateContributionMeansRequest:
    """Input DTO for PUT/PATCH /workspaces/contribution-means/<id>/ endpoint.

    Handles contribution means updates.
    """
    name: str | None = None
    icon: str | None = None
    description: str | None = None
    is_active: bool | None = None
    order: int | None = None
