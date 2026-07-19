"""Use case: fetch messages for a conversation with access control."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.messaging.domain.entities.message_entity import Message
from components.messaging.domain.errors import ConversationNotFoundError


@dataclass
class GetConversationMessagesUseCase:
    conversation_repo: object  # ConversationRepositoryPort
    message_repo: object  # MessageRepositoryPort

    def execute(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        limit: int = 50,
        before: UUID | None = None,
    ) -> list[Message]:
        conversation = self.conversation_repo.find_by_id(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} not found."
            )
        # Verify the caller is a participant.
        conversation.ensure_participant(user_id)

        return self.message_repo.list_for_conversation(
            conversation_id, limit=limit, before=before,
        )
