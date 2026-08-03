"""ORM adapter implementing :class:`ChatConversationStorePort`.

Persists + reads the chat use case's user-facing ``Conversation`` /
``ConversationMessage`` rows — the exact ORM logic ``agent_chat_use_case`` did in
its module-level helpers, moved behind the port so the use case no longer imports
persistence. Every method keeps the prior best-effort contract (swallow, return
the fallback) so a persistence hiccup never breaks a working chat.
"""

from __future__ import annotations

import logging

from components.agents.application.ports.chat_conversation_store_port import ChatConversationStorePort

logger = logging.getLogger(__name__)


class OrmChatConversationStoreRepository(ChatConversationStorePort):
    def ensure_conversation_with_user_message(
        self,
        *,
        conversation_id: str | None,
        user_id: str,
        workspace_id: str,
        agent_type: str,
        query: str,
    ) -> str | None:
        try:
            from infrastructure.persistence.ai.conversations.models import (
                Conversation,
                ConversationMessage,
            )
        except Exception:
            logger.exception("Could not import Conversation models for chat persistence")
            return conversation_id

        try:
            conversation = None
            if conversation_id:
                conversation = Conversation.objects.filter(id=conversation_id).first()
            if conversation is None:
                conversation = Conversation.objects.create(
                    id=conversation_id or None,
                    user_id=user_id,
                    title=(query or "").strip()[:80] or "Chat",
                    metadata={
                        "workspace_id": workspace_id,
                        "agent_type": agent_type,
                        "source": "agent_chat",
                    },
                )
            ConversationMessage.objects.create(
                conversation=conversation,
                role="human",
                content=query or "",
            )
            return str(conversation.id)
        except Exception:
            logger.exception("Failed to persist user chat message for workspace %s", workspace_id)
            return conversation_id

    def append_assistant_message(
        self,
        *,
        conversation_id: str | None,
        content: str,
        metadata: dict | None = None,
    ) -> str | None:
        if not conversation_id or not content:
            return None
        try:
            from infrastructure.persistence.ai.conversations.models import (
                Conversation,
                ConversationMessage,
            )

            conversation = Conversation.objects.filter(id=conversation_id).first()
            if conversation is None:
                return None
            message = ConversationMessage.objects.create(
                conversation=conversation,
                role="assistant",
                content=content,
                metadata=metadata or {},
            )
            return str(message.id)
        except Exception:
            logger.exception("Failed to persist assistant chat message for conversation %s", conversation_id)
            return None

    def get_conversation_pdf_id(self, conversation_id: str | None) -> str | None:
        if not conversation_id:
            return None
        try:
            from infrastructure.persistence.ai.conversations.models import Conversation
        except Exception:
            return None
        try:
            row = Conversation.objects.filter(id=conversation_id).only("metadata").first()
        except Exception:
            return None
        if row is None or not isinstance(row.metadata, dict):
            return None
        pdf_id = row.metadata.get("pdf_id")
        return str(pdf_id) if pdf_id else None

    def load_recent_turns(self, conversation_id: str | None, *, limit: int) -> list[tuple[str, str]]:
        if not conversation_id:
            return []
        try:
            from infrastructure.persistence.ai.conversations.models import ConversationMessage
        except Exception:
            logger.exception("Could not import ConversationMessage for chat history load")
            return []
        try:
            # Order DESC for the LIMIT; the caller reverses to chronological.
            rows = (
                ConversationMessage.objects.filter(conversation_id=conversation_id)
                .order_by("-created_at")
                .values_list("role", "content")[:limit]
            )
            return [(role, content) for role, content in rows]
        except Exception:
            logger.exception("Failed to load conversation history for %s", conversation_id)
            return []
