"""Port definitions for the messaging bounded context.

Ports define the abstract interfaces that the application layer depends on.
Infrastructure adapters provide concrete implementations.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from components.messaging.domain.entities.conversation_entity import Conversation, Participant
from components.messaging.domain.entities.message_entity import Message


class ConversationRepositoryPort(Protocol):
    """Persistence port for conversations."""

    def find_by_id(self, conversation_id: UUID) -> Conversation | None: ...

    def find_private_between(
        self,
        user_id: UUID,
        other_user_id: UUID,
        workspace_id: UUID | None = None,
    ) -> Conversation | None: ...

    def list_for_user(
        self,
        user_id: UUID,
        *,
        include_archived: bool = False,
        starred_only: bool = False,
    ) -> list:  # list[ConversationListItem] — enriched read model
        ...

    def create(self, conversation: Conversation) -> Conversation: ...

    def update_participant_state(
        self,
        conversation_id: UUID,
        user_id: UUID,
        **fields,
    ) -> Participant: ...


class WorkspaceMembershipCheckPort(Protocol):
    """Driven port answering "do these two users share a workspace?".

    Direct messaging is gated on workspace-membership overlap. The
    concrete adapter delegates to the platform-wide workspace-access
    lookup in ``shared_platform`` so messaging never imports another
    context's ORM directly.
    """

    def shares_workspace(self, user_a: UUID, user_b: UUID) -> bool: ...


class MessageRepositoryPort(Protocol):
    """Persistence port for messages."""

    def find_by_id(self, message_id: UUID) -> Message | None: ...

    def list_for_conversation(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
        before: UUID | None = None,
    ) -> list[Message]: ...

    def create(self, message: Message) -> Message: ...

    def soft_delete(self, message_id: UUID, user_id: UUID) -> bool: ...

    def mark_read(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> int:
        """Mark all unread messages in a conversation as read.
        Returns the number of messages marked."""
        ...

    def unread_count(self, user_id: UUID) -> dict[UUID, int]:
        """Return a mapping of conversation_id → unread count for the user."""
        ...
