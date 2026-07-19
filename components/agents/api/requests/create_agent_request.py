"""Request DTO for POST /ai/agents/create/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateAgentRequest:
    """Input DTO for POST /ai/agents/create/ endpoint.

    Creates a new AI agent with specified configuration.
    """
    agent_type: str
    workspace_id: str
    config: dict[str, Any] = field(default_factory=dict)
    department_id: str | None = None
    team_id: str | None = None
