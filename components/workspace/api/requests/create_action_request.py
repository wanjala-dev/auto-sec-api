"""Request DTO for action endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateActionRequest:
    """Input DTO for POST /workspaces/actions/ endpoint.

    Handles action creation for workspaces.
    """
    title: str
    workspace: str
    owner: str
    privacy: str | None = None
    url: str | None = None
    created_date: str | None = None
