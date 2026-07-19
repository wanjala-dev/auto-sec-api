"""
Ports for conversation and message persistence.

These abstract the ORM calls that the agents controller and service
currently make directly against Conversation / ConversationMessage models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConversationRepositoryPort(ABC):
    """Read/write access to conversation entities."""

    @abstractmethod
    def get_by_id(self, conversation_id: str, *, user: Any) -> Any | None:
        """Return a conversation owned by *user*, or *None*."""

    @abstractmethod
    def list_for_user(self, user: Any) -> Any:
        """Return a queryset/list of conversations for *user*."""

    @abstractmethod
    def create(self, **kwargs: Any) -> Any:
        """Create and return a new Conversation."""

    @abstractmethod
    def delete(self, conversation_id: str, *, user: Any) -> bool:
        """Delete a conversation and its messages.  Return *True* on success."""

    @abstractmethod
    def clear_messages(self, conversation_id: str, *, user: Any) -> bool:
        """Delete all messages in a conversation without deleting the conversation."""

    @abstractmethod
    def find_document_assist(self, *, user: Any, artifact_type: str, artifact_id: str) -> Any | None:
        """Return the user's document-assist conversation for an artifact
        (the per-document in-editor assist thread), or *None*. Scoped by
        the ``surface='document_assist'`` metadata marker so it never
        collides with a normal chat conversation."""

    @abstractmethod
    def list_messages(self, conversation: Any) -> Any:
        """Return the conversation's messages, oldest first, with feedback
        prefetched for aggregate counts."""


class ConversationMessageRepositoryPort(ABC):
    """Read/write access to conversation messages."""

    @abstractmethod
    def create_message(self, *, conversation: Any, role: str, content: str, **kwargs: Any) -> Any:
        """Persist a new message and return it."""

    @abstractmethod
    def update_streaming_status(self, message: Any, *, content: str, is_streaming: bool) -> None:
        """Update a message's content and streaming flag."""
