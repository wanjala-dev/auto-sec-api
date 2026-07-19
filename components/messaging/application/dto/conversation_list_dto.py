"""Read-model DTOs for messaging list projections.

These are plain application-layer dataclasses (not domain entities and
not presentation resources) so the ORM repository may build and return
them, and the controller/serializer may consume them, without either
layer importing the other. They exist to let the conversation-list
endpoint answer in a single round-trip — carrying the other
participant's display fields, a last-message preview, and the viewer's
unread count alongside the ``Conversation`` entity — instead of forcing
the frontend into an N+1 of follow-up lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.messaging.domain.entities.conversation_entity import Conversation


@dataclass
class ParticipantSummary:
    """Display fields for a conversation participant."""

    user_id: UUID
    display_name: str = ""
    avatar_url: str = ""
    initials: str = ""


@dataclass
class LastMessagePreview:
    """The most recent (non-deleted) message in a conversation."""

    id: UUID
    sender_id: UUID
    body: str
    message_type: str
    created_at: datetime | None = None


@dataclass
class ConversationListItem:
    """A conversation enriched for the list view.

    ``other_participant`` is the 1:1 counterpart from the viewer's
    perspective (None for a solo/degenerate conversation).
    """

    conversation: Conversation
    other_participant: ParticipantSummary | None = None
    last_message: LastMessagePreview | None = None
    unread_count: int = 0
