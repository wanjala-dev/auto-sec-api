"""Port for conversation persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.agents.domain.entities.conversation_entity import (
    ConversationEntity,
    ConversationMessageEntity,
)


class ConversationRepositoryPort(ABC):

    @abstractmethod
    def find_by_id(self, conversation_id: UUID) -> ConversationEntity | None: ...

    @abstractmethod
    def find_by_pdf_id(self, pdf_id: str) -> ConversationEntity | None: ...

    @abstractmethod
    def create(
        self,
        *,
        user_id: UUID | None = None,
        title: str = "",
        metadata: dict | None = None,
    ) -> ConversationEntity: ...

    @abstractmethod
    def add_message(
        self,
        conversation_id: UUID,
        *,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ConversationMessageEntity: ...

    @abstractmethod
    def list_messages(
        self,
        conversation_id: UUID,
        *,
        limit: int | None = None,
    ) -> list[ConversationMessageEntity]: ...
