"""Request DTO for PATCH /ai/agents/<id>/profile/update/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PatchAgentProfileRequest:
    """Input DTO for PATCH /ai/agents/<id>/profile/update/ endpoint.

    Updates agent profile fields like name, description, etc.
    """
    data: dict[str, Any] = field(default_factory=dict)
