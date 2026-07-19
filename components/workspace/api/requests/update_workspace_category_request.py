"""Request DTO for workspace category update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UpdateWorkspaceCategoryRequest:
    """Input DTO for PUT/PATCH /workspaces/category/detail/<id>/ endpoint.

    Handles workspace category updates.
    """
    name: str | None = None
