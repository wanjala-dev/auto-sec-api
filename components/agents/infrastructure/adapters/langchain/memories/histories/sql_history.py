"""SQL Message History for conversation persistence.

Replaces raw SQL (``connection.cursor()``) with Django ORM calls through
lazy-imported models.  This keeps the module loadable without pulling the
full model graph at import time.
"""
import logging
from typing import List, Optional

from langchain.schema import AIMessage, BaseChatMessageHistory, BaseMessage, HumanMessage, SystemMessage
# Use LangChain's Pydantic v1 shim to avoid v2 property resolution issues.
from langchain_core.pydantic_v1 import BaseModel

logger = logging.getLogger(__name__)


def _get_conversation_models():
    """Lazy import Conversation and ConversationMessage ORM models."""
    from infrastructure.persistence.ai.conversations.models import (
        Conversation,
        ConversationMessage,
    )
    return Conversation, ConversationMessage


class SqlMessageHistory(BaseChatMessageHistory, BaseModel):
    """SQL-based message history for conversations.

    NOTE: This class can optionally cap the message count and content length
    returned to LLM memory so long conversations do not exceed model limits.
    """

    conversation_id: str
    max_messages: Optional[int] = None
    max_message_chars: Optional[int] = None
    max_total_chars: Optional[int] = None

    def __init__(self, **data):  # type: ignore[override]
        super().__init__(**data)
        try:
            self._ensure_conversation_exists()
        except Exception:  # pragma: no cover - defensive only
            logger.exception("Failed to ensure conversation %s exists", getattr(self, 'conversation_id', '<unknown>'))

    @property
    def messages(self) -> List[BaseMessage]:
        """Get all messages for this conversation"""
        _, ConversationMessage = _get_conversation_models()

        qs = ConversationMessage.objects.filter(
            conversation_id=self.conversation_id,
        ).values_list("role", "content", "created_at")

        if self.max_messages:
            # Get last N messages (DESC then reverse)
            rows = list(
                qs.order_by("-created_at")[:self.max_messages]
            )
            rows.reverse()
        else:
            rows = list(qs.order_by("created_at"))

        messages = []
        for role, content, created_at in rows:
            content = content or ""
            if self.max_message_chars and len(content) > self.max_message_chars:
                content = f"{content[:self.max_message_chars].rstrip()}..."

            if role == 'human':
                messages.append(HumanMessage(content=content))
            elif role == 'assistant':
                messages.append(AIMessage(content=content))
            elif role == 'system':
                messages.append(SystemMessage(content=content))

        if self.max_total_chars:
            budget = max(int(self.max_total_chars), 0)
            if budget > 0 and messages:
                trimmed = []
                total = 0
                for msg in reversed(messages):
                    total += len(msg.content)
                    if total > budget and trimmed:
                        break
                    trimmed.append(msg)
                messages = list(reversed(trimmed))

        return messages

    def add_message(self, message: BaseMessage) -> None:
        """Add a message to the conversation"""
        try:
            self._ensure_conversation_exists()
            _, ConversationMessage = _get_conversation_models()

            # Determine role from message type
            if isinstance(message, HumanMessage):
                role = 'human'
            elif isinstance(message, AIMessage):
                role = 'assistant'
            elif isinstance(message, SystemMessage):
                role = 'system'
            else:
                role = 'human'  # Default fallback

            ConversationMessage.objects.create(
                conversation_id=self.conversation_id,
                role=role,
                content=message.content,
                metadata={},
            )
        except Exception as exc:  # pragma: no cover - database failure
            logger.exception("SqlMessageHistory.add_message: Failed to add message: %s", exc)
            raise

    def clear(self) -> None:
        """Clear all messages for this conversation"""
        _, ConversationMessage = _get_conversation_models()
        ConversationMessage.objects.filter(conversation_id=self.conversation_id).delete()

    # Override additional BaseChatMessageHistory methods to ensure UUID generation
    def add_user_message(self, content: str) -> None:
        """Add user message (Override to ensure UUID generation)"""
        self.add_message(HumanMessage(content=content))

    def add_ai_message(self, content: str) -> None:
        """Add AI message (Override to ensure UUID generation)"""
        self.add_message(AIMessage(content=content))

    def add_system_message(self, content: str) -> None:
        """Add system message (Override to ensure UUID generation)"""
        self.add_message(SystemMessage(content=content))

    def add_messages(self, messages: List[BaseMessage]) -> None:
        """Add multiple messages (Override to ensure UUID generation)"""
        for message in messages:
            self.add_message(message)

    def get_messages_by_conversation_id(self, conversation_id: str) -> List[BaseMessage]:
        """Get messages for a specific conversation ID"""
        _, ConversationMessage = _get_conversation_models()
        rows = ConversationMessage.objects.filter(
            conversation_id=conversation_id,
        ).order_by("created_at").values_list("role", "content")

        messages = []
        for role, content in rows:
            if role == 'human':
                messages.append(HumanMessage(content=content))
            elif role == 'assistant':
                messages.append(AIMessage(content=content))
            elif role == 'system':
                messages.append(SystemMessage(content=content))
        return messages

    def _ensure_conversation_exists(self) -> None:
        """Ensure the conversation exists in the database before adding messages"""
        Conversation, _ = _get_conversation_models()

        try:
            Conversation.objects.get(id=self.conversation_id)
        except Conversation.DoesNotExist:
            metadata = {'source': 'sql_message_history_fallback'}
            Conversation.objects.create(
                id=self.conversation_id,
                user_id=None,
                title="Agent Conversation",
                metadata=metadata,
            )
            logger.info("Created conversation %s with fallback metadata", self.conversation_id)
