"""Request DTO for workspace operation update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateWorkspaceOperationRequest:
    """Input DTO for PATCH /workspaces/<workspace>/operations/<id> endpoint.

    Handles workspace operation updates.
    """
    name: str | None = None
    checked: bool | None = None
    text: str | None = None
