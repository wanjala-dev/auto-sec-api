"""Request DTO for POST /ai/conversations/<id>/messages/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AddConversationMessageRequest:
    """Input DTO for POST /ai/conversations/<id>/messages/ endpoint.

    Adds a message to a conversation.
    """
    role: str = "human"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
