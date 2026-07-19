"""Pure domain entities for AI conversations and messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ConversationEntity:
    id: UUID
    title: str
    is_active: bool = True
    user_id: UUID | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def pdf_id(self) -> str | None:
        return self.metadata.get("pdf_id")


@dataclass(frozen=True)
class ConversationMessageEntity:
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
