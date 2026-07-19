"""
Port for agent conversation memory.

Abstracts how conversation history is stored, retrieved, and fed back
into the agent runtime.  LangChain uses ``ConversationBufferMemory``;
LlamaIndex uses ``ChatMemoryBuffer``; a custom framework might use a
simple list of dicts.  This port hides those differences.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Value objects ─────────────────────────────────────────────────────

@dataclass
class MemoryMessage:
    """A single message in a conversation, framework-agnostic."""

    role: str          # "human" | "ai" | "system"
    content: str
    created_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryStats:
    """Aggregate statistics about a conversation's memory."""

    total_messages: int = 0
    human_messages: int = 0
    ai_messages: int = 0
    system_messages: int = 0
    last_activity: Optional[str] = None


@dataclass
class MemoryHandle:
    """Opaque handle wrapping a framework-specific memory instance.

    Passed back into ``AgentRuntimePort.execute()`` so the runtime can
    attach it to its executor.  Only the adapter that created it knows
    the concrete type inside ``_impl``.
    """

    conversation_id: str
    _impl: Any = field(repr=False, default=None)


# ── Port contract ─────────────────────────────────────────────────────

class AgentMemoryPort(ABC):
    """
    Contract for agent conversation-memory management.

    Adapters live at ``infrastructure/adapters/<framework>/memory.py``.
    """

    @abstractmethod
    def get_or_create_conversation_id(
        self,
        agent_id: str,
        *,
        thread_id: Optional[str] = None,
    ) -> str:
        """Return (or create) a conversation ID for the given agent/thread."""

    @abstractmethod
    def build_memory(
        self,
        conversation_id: str,
        *,
        memory_type: str = "buffer",
        max_messages: Optional[int] = None,
        max_message_chars: Optional[int] = None,
        max_total_chars: Optional[int] = None,
        system_message: Optional[str] = None,
        **kwargs: Any,
    ) -> MemoryHandle:
        """Build a framework-specific memory object and return an opaque handle."""

    @abstractmethod
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        """Persist a message to the conversation history."""

    @abstractmethod
    def get_history(
        self,
        conversation_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MemoryMessage]:
        """Retrieve conversation history, most recent first."""

    @abstractmethod
    def record_execution(
        self,
        agent_id: str,
        conversation_id: str,
        *,
        query: str,
        response: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a complete agent execution (query + response pair)."""

    @abstractmethod
    def get_stats(self, conversation_id: str) -> MemoryStats:
        """Return aggregate statistics for a conversation."""

    def clear(self, conversation_id: str) -> None:
        """Delete all messages in a conversation. Default: no-op."""
