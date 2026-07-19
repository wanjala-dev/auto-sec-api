"""Request DTO for action update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateActionRequest:
    """Input DTO for PUT/PATCH /workspaces/actions/<id>/ endpoint.

    Handles action updates.
    """
    title: str | None = None
    privacy: str | None = None
    url: str | None = None
    created_date: str | None = None
