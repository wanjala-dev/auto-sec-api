"""Port: the chat use case's own ``Conversation`` / ``ConversationMessage`` writes + reads.

``AgentChatUseCase`` persists the user-facing conversation (create-or-get, append
user + assistant messages), reads the conversation's ``pdf_id`` (to scope RAG),
and loads recent turns for the planner. All of that used to hit
``infrastructure.persistence.ai.conversations`` ORM directly from the application
layer (Rule-2 violation). This port is the sanctioned seam; the ORM lives in the
adapter.

Every method preserves the use case's existing best-effort contract: a failure
returns the caller's fallback (the passed-in ``conversation_id`` / ``None`` / an
empty history) so a persistence hiccup never breaks a chat that otherwise works.
The port speaks in plain values (ids, role/content tuples) — no ORM instance
crosses the seam.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ChatConversationStorePort(ABC):
    """Read/write the chat use case's user-facing conversation + messages."""

    @abstractmethod
    def ensure_conversation_with_user_message(
        self,
        *,
        conversation_id: str | None,
        user_id: str,
        workspace_id: str,
        agent_type: str,
        query: str,
    ) -> str | None:
        """Create-or-get the user-facing conversation and append the user query.

        Returns the conversation id (the passed-in one when persistence fails).
        """

    @abstractmethod
    def append_assistant_message(
        self,
        *,
        conversation_id: str | None,
        content: str,
        metadata: dict | None = None,
    ) -> str | None:
        """Append an assistant message; return its id (``None`` on no-op/failure)."""

    @abstractmethod
    def get_conversation_pdf_id(self, conversation_id: str | None) -> str | None:
        """Return the ``pdf_id`` stored on the conversation's metadata, or ``None``."""

    @abstractmethod
    def load_recent_turns(self, conversation_id: str | None, *, limit: int) -> list[tuple[str, str]]:
        """Return up to ``limit`` most-recent ``(role, content)`` turns, newest
        first (the caller reverses to chronological). Best-effort — ``[]`` on
        failure.
        """
