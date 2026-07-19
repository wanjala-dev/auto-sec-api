"""Request DTO for POST /ai/agents/<id>/rating/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateAgentRequest:
    """Input DTO for POST /ai/agents/<id>/rating/ endpoint.

    Rates an agent with a numerical score and optional comment.
    """
    score: int
    comment: str = ""
