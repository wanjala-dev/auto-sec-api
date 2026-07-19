"""Request DTO for POST /ai/agents/<id>/share/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShareAgentRequest:
    """Input DTO for POST /ai/agents/<id>/share/ endpoint.

    Creates a share token for an agent with specified scope and expiration.
    """
    scope: str
    expires_at: Any | None = None
