"""Request DTO for workspace operation endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateWorkspaceOperationRequest:
    """Input DTO for POST /workspaces/operations/ endpoint.

    Handles workspace operation creation.
    """
    name: str
    workspace: str
    checked: bool = False
    text: str | None = None
