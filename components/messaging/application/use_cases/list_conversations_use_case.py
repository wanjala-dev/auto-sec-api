"""Use case: list conversations for a user."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.messaging.application.dto.conversation_list_dto import (
    ConversationListItem,
)


@dataclass
class ListConversationsUseCase:
    conversation_repo: object  # ConversationRepositoryPort
    message_repo: object  # MessageRepositoryPort

    def execute(
        self,
        *,
        user_id: UUID,
        include_archived: bool = False,
        starred_only: bool = False,
    ) -> list[ConversationListItem]:
        return self.conversation_repo.list_for_user(
            user_id,
            include_archived=include_archived,
            starred_only=starred_only,
        )
