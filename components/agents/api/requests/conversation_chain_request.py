"""Request DTO for POST /ai/chains/conversation/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConversationChainRequest:
    """Input DTO for POST /ai/chains/conversation/ endpoint.

    Executes a conversation chain with memory management.
    """
    message: str
    conversation_id: str | None = None
    memory_type: str = "buffer"
    config: dict[str, Any] = field(default_factory=dict)
