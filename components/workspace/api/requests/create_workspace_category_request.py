"""Request DTO for workspace category endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateWorkspaceCategoryRequest:
    """Input DTO for POST /workspaces/category/ endpoint.

    Handles workspace category creation.
    """
    name: str
