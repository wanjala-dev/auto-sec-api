"""Request DTO for POST /ai/conversations/create/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateConversationRequest:
    """Input DTO for POST /ai/conversations/create/ endpoint.

    Creates a new conversation for memory or PDF chat.
    """
    title: str = "New Conversation"
    workspace_id: str | None = None
    pdf_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
