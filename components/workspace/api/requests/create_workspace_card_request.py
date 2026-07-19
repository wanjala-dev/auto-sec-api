"""Request DTO for workspace card endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateWorkspaceCardRequest:
    """Input DTO for POST /workspaces/cards/ endpoint.

    Handles workspace card creation for visual workspace representations.
    """
    workspace: str
    name: str
    checked: bool = False
    text: str | None = None
    photo_url: str | None = None
