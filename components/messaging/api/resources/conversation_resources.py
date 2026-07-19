"""Output DTOs for conversation endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ParticipantResource:
    """Output DTO for a participant within a conversation."""

    user_id: UUID
    role: str
    is_archived: bool = False
    is_starred: bool = False
    is_muted: bool = False
    last_read_at: datetime | None = None
    joined_at: datetime | None = None


@dataclass(frozen=True)
class ParticipantSummaryResource:
    """Display fields for the conversation's other participant."""

    user_id: UUID
    display_name: str = ""
    avatar_url: str = ""
    initials: str = ""


@dataclass(frozen=True)
class LastMessageResource:
    """Preview of the most recent message in a conversation."""

    id: UUID
    sender_id: UUID
    body: str
    message_type: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class ConversationResource:
    """Output DTO for a conversation.

    ``other_participant`` / ``last_message`` / ``unread_count`` are the
    list-view enrichment (null/0 on the start-conversation response,
    populated by the list endpoint) so the inbox renders in one call.
    """

    id: UUID
    conversation_type: str
    workspace_id: UUID | None = None
    participants: list[ParticipantResource] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    other_participant: ParticipantSummaryResource | None = None
    last_message: LastMessageResource | None = None
    unread_count: int = 0


@dataclass(frozen=True)
class ConversationStartResource:
    """Output DTO for the start-conversation response."""

    conversation: ConversationResource
    created: bool = False


@dataclass(frozen=True)
class ConversationManageResource:
    """Output DTO for archive/star/mute toggle responses."""

    conversation_id: UUID
    is_archived: bool = False
    is_starred: bool = False
    is_muted: bool = False
