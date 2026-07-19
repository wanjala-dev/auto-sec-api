"""Request DTO for workspace contribution means endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssignContributionMeansRequest:
    """Input DTO for POST /workspaces/assign-contribution-means/ endpoint.

    Handles assignment of contribution means to workspaces.
    """
    workspace: str
    means: list[int]
