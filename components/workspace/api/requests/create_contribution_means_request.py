"""Request DTO for contribution means endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateContributionMeansRequest:
    """Input DTO for POST /workspaces/contribution-means/ endpoint.

    Handles contribution means creation.
    """
    name: str
    icon: str | None = None
    description: str | None = None
    is_active: bool = True
    order: int | None = None
