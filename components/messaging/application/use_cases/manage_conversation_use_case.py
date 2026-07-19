"""Use cases: archive, star, mute a conversation (per-participant)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.messaging.domain.entities.conversation_entity import Participant
from components.messaging.domain.errors import ConversationNotFoundError


@dataclass
class _BaseManageUseCase:
    conversation_repo: object  # ConversationRepositoryPort

    def _ensure_exists_and_participant(self, conversation_id: UUID, user_id: UUID):
        conversation = self.conversation_repo.find_by_id(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} not found."
            )
        conversation.ensure_participant(user_id)
        return conversation


@dataclass
class ArchiveConversationUseCase(_BaseManageUseCase):
    def execute(self, *, conversation_id: UUID, user_id: UUID, archive: bool = True) -> Participant:
        self._ensure_exists_and_participant(conversation_id, user_id)
        return self.conversation_repo.update_participant_state(
            conversation_id, user_id, is_archived=archive,
        )


@dataclass
class StarConversationUseCase(_BaseManageUseCase):
    def execute(self, *, conversation_id: UUID, user_id: UUID, star: bool = True) -> Participant:
        self._ensure_exists_and_participant(conversation_id, user_id)
        return self.conversation_repo.update_participant_state(
            conversation_id, user_id, is_starred=star,
        )


@dataclass
class MuteConversationUseCase(_BaseManageUseCase):
    def execute(self, *, conversation_id: UUID, user_id: UUID, mute: bool = True) -> Participant:
        self._ensure_exists_and_participant(conversation_id, user_id)
        return self.conversation_repo.update_participant_state(
            conversation_id, user_id, is_muted=mute,
        )
