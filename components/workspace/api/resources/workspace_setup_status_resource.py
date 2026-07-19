"""Resource DTO for workspace setup status endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceSetupCheckResource:
    """Output DTO for individual setup check status."""
    code: str | None = None
    label: str | None = None
    is_complete: bool = False
    detail: str | None = None


@dataclass(frozen=True)
class WorkspaceSetupRecommendationResource:
    """Output DTO for setup recommendations."""
    code: str | None = None
    message: str | None = None
    severity: str | None = None
    scope: str | None = None


@dataclass(frozen=True)
class WorkspaceSetupStatusResource:
    """Output DTO for workspace setup status endpoints.

    Represents the setup progress and recommendations for a workspace.
    """
    workspace: str | None = None
    workspace_name: str | None = None
    is_complete: bool = False
    checks: list[WorkspaceSetupCheckResource] | None = None
    pending: list[str] | None = None
    recommendations: list[WorkspaceSetupRecommendationResource] | None = None
