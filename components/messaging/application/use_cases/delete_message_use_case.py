"""Use case: soft-delete a message."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.messaging.domain.errors import (
    ConversationNotFoundError,
    MessageNotFoundError,
)


@dataclass
class DeleteMessageUseCase:
    conversation_repo: object  # ConversationRepositoryPort
    message_repo: object  # MessageRepositoryPort

    def execute(self, *, message_id: UUID, user_id: UUID) -> bool:
        message = self.message_repo.find_by_id(message_id)
        if message is None:
            raise MessageNotFoundError(f"Message {message_id} not found.")

        # Verify user is a participant in the conversation.
        conversation = self.conversation_repo.find_by_id(message.conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(
                f"Conversation {message.conversation_id} not found."
            )
        conversation.ensure_participant(user_id)

        # Only the sender can delete their own message.
        if message.sender_id != user_id:
            raise MessageNotFoundError("You can only delete your own messages.")

        return self.message_repo.soft_delete(message_id, user_id)
