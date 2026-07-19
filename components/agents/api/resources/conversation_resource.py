"""Response DTO for conversation endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConversationMessageResource:
    """A single message in a conversation."""
    message_id: str | None = None
    id: str | None = None
    role: str = "human"
    content: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationResource:
    """Output DTO for conversation detail endpoints."""
    conversation_id: str
    id: str | None = None
    title: str = "Conversation"
    created_at: str | None = None
    updated_at: str | None = None
    is_active: bool = True
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    messages: list[ConversationMessageResource] = field(default_factory=list)


@dataclass(frozen=True)
class ConversationCollectionResource:
    """Output DTO for conversation list endpoints."""
    conversations: list[ConversationResource] = field(default_factory=list)
    total: int = 0
    count: int = 0
    next_url: str | None = None
    previous_url: str | None = None
