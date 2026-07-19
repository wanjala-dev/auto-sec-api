"""Request DTO for starting a conversation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class StartConversationRequest:
    """Input DTO for starting a private conversation."""

    recipient_id: UUID
    workspace_id: UUID | None = None
