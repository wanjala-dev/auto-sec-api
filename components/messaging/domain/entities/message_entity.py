"""Message entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from components.messaging.domain.errors import MessageBodyEmptyError
from components.messaging.domain.value_objects import MessageType


@dataclass
class Message:
    """An individual message within a conversation."""

    id: UUID | None = None
    conversation_id: UUID | None = None
    sender_id: UUID | None = None
    body: str = ""
    message_type: str = MessageType.TEXT
    image: str | None = None
    # Structured card payload (e.g. {"share": {...}}) — see the ORM model.
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None

    def validate(self) -> None:
        """Enforce message invariants before persistence."""
        if self.message_type == MessageType.TEXT:
            if not self.body or not self.body.strip():
                raise MessageBodyEmptyError("Message body cannot be empty.")
        if not isinstance(self.metadata, dict):
            raise MessageBodyEmptyError("Message metadata must be an object.")
