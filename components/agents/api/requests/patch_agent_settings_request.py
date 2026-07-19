"""Request DTO for PATCH /ai/agents/<id>/settings/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PatchAgentSettingsRequest:
    """Input DTO for PATCH /ai/agents/<id>/settings/ endpoint.

    Updates agent custom settings and configuration flags.
    """
    data: dict[str, Any] = field(default_factory=dict)
