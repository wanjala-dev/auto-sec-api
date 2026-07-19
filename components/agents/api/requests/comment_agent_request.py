"""Request DTO for POST /ai/agents/<id>/comments/create/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommentAgentRequest:
    """Input DTO for POST /ai/agents/<id>/comments/create/ endpoint.

    Adds a comment to an agent, optionally as a reply to another comment.
    """
    body: str
    parent: Any | None = None
