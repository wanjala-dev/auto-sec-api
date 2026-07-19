"""Request DTO for POST /ai/agents/<id>/execute/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecuteAgentRequest:
    """Input DTO for POST /ai/agents/<id>/execute/ endpoint.

    Executes a query with an AI agent.
    """
    query: str
