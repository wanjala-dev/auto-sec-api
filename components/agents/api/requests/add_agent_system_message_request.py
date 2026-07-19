"""Request DTO for POST /ai/agents/<id>/memory/system-message/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AddAgentSystemMessageRequest:
    """Input DTO for POST /ai/agents/<id>/memory/system-message/ endpoint.

    Adds a system message to an agent's memory for context.
    """
    content: str
