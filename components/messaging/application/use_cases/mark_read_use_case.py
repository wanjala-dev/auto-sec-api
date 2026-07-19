"""Use case: mark messages in a conversation as read."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.messaging.domain.errors import ConversationNotFoundError


@dataclass
class MarkReadUseCase:
    conversation_repo: object  # ConversationRepositoryPort
    message_repo: object  # MessageRepositoryPort

    def execute(self, *, conversation_id: UUID, user_id: UUID) -> int:
        conversation = self.conversation_repo.find_by_id(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} not found."
            )
        conversation.ensure_participant(user_id)
        return self.message_repo.mark_read(conversation_id, user_id)
