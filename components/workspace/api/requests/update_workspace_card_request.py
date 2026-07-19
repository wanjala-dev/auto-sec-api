"""Request DTO for workspace card update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateWorkspaceCardRequest:
    """Input DTO for PATCH /workspaces/<workspace>/cards/ endpoint.

    Handles workspace card updates.
    """
    name: str | None = None
    checked: bool | None = None
    text: str | None = None
    photo_url: str | None = None
