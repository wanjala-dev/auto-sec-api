"""Request DTOs for category endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateCategoryRequest:
    """Input DTO for POST /categories/ endpoint."""
    name: str
