"""Output DTOs for message endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class MessageResource:
    """Output DTO for a single message."""

    id: UUID
    conversation_id: UUID
    sender_id: UUID
    body: str
    message_type: str = "text"
    image: str | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_deleted: bool = False


@dataclass(frozen=True)
class UnreadCountResource:
    """Output DTO for unread counts per conversation."""

    conversation_id: UUID
    count: int = 0
