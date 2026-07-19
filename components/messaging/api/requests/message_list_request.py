"""Request DTO for listing messages in a conversation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MessageListRequest:
    """Input DTO for fetching paginated messages."""

    limit: int = 50
    before: UUID | None = None
