"""Native conversation-memory objects (LangChain 1.x migration, 2026-07-19).

LangChain 1.x removed ``ConversationBufferMemory`` / ``ConversationBufferWindowMemory``
(and ``create_agent`` takes no ``memory=`` argument at all). The replacement in this
codebase is **SQL-history threading**: ``BaseAgent``'s ``_GraphExecutorHandle`` calls
``memory.load_messages()`` before every graph invoke and prepends the returned window
to the input messages. Persistence of new turns is owned by
``memory_service.record_execution`` (as it always was) — these objects are read-side
loaders, not write-through buffers, so the 0.3 ``save_context`` monkeypatch surface
is gone entirely.

Design notes:
- ``chat_memory`` stays the attribute name for the underlying ``SqlMessageHistory``
  because ``BaseAgent._apply_run_context`` re-points ``chat_memory.conversation_id``
  and per-run memory limits through it.
- ``k`` mirrors the old ``ConversationBufferWindowMemory`` semantics: keep the last
  ``k`` exchanges (2·k messages). ``None`` = full (character-capped) buffer.
- ``CompactingConversationMemory`` preserves the compacting behaviour: overflow
  beyond the window is summarised into one system message (LLM-backed, truncation
  fallback) instead of being dropped.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage

from .histories.sql_history import SqlMessageHistory

logger = logging.getLogger(__name__)

_COMPACT_PROMPT = (
    "Summarize the following conversation history into a concise paragraph. "
    "Preserve key facts, decisions, action items, and user preferences. "
    "Omit greetings, filler, and repetition.\n\n"
    "{history}"
)


class SqlConversationMemory:
    """Full-buffer conversation memory backed by ``SqlMessageHistory``.

    The history object itself enforces ``max_messages`` / ``max_message_chars`` /
    ``max_total_chars``, so the full buffer is already bounded.
    """

    def __init__(self, chat_memory: SqlMessageHistory):
        self.chat_memory = chat_memory

    @property
    def conversation_id(self) -> str | None:
        return getattr(self.chat_memory, "conversation_id", None)

    def load_messages(self) -> list[BaseMessage]:
        """The prior-turn messages to thread into the agent graph input."""
        try:
            return list(self.chat_memory.messages)
        except Exception:
            logger.warning("conversation memory load failed; continuing without history", exc_info=True)
            return []


class SqlWindowConversationMemory(SqlConversationMemory):
    """Window memory — keep the last ``k`` exchanges (2·k messages)."""

    def __init__(self, chat_memory: SqlMessageHistory, k: int = 2):
        super().__init__(chat_memory)
        self.k = max(int(k), 1)

    def load_messages(self) -> list[BaseMessage]:
        messages = super().load_messages()
        window = self.k * 2
        if window and len(messages) > window:
            messages = messages[-window:]
        return messages


class CompactingConversationMemory(SqlWindowConversationMemory):
    """Window memory that compacts overflow into a summary instead of dropping it.

    When history exceeds the ``k``-exchange window, the overflow messages are
    summarised (via ``compaction_llm``) into a single system message prepended to
    the window. With no LLM available it degrades to plain windowing — same
    behaviour as the 0.3 ``CompactingMemory`` fallback.
    """

    def __init__(self, chat_memory: SqlMessageHistory, k: int = 5, compaction_llm: Any = None):
        super().__init__(chat_memory, k=k)
        self.compaction_llm = compaction_llm
        self._summary_cache: str = ""

    def load_messages(self) -> list[BaseMessage]:
        all_messages = SqlConversationMemory.load_messages(self)
        window = self.k * 2
        if len(all_messages) <= window:
            return self._with_summary(all_messages)

        overflow, kept = all_messages[:-window], all_messages[-window:]
        if self.compaction_llm is not None and overflow:
            self._compact(overflow)
        return self._with_summary(kept)

    def _with_summary(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        if not self._summary_cache:
            return messages
        summary_msg = SystemMessage(content=f"[Conversation summary from earlier messages]\n{self._summary_cache}")
        return [summary_msg, *messages]

    def _compact(self, overflow: list[BaseMessage]) -> None:
        """Summarise dropped messages into a running summary. Never raises."""
        try:
            history_text = "\n".join(f"{msg.type}: {str(msg.content)[:500]}" for msg in overflow)
            if self._summary_cache:
                history_text = f"Previous summary: {self._summary_cache}\n\n{history_text}"
            response = self.compaction_llm.invoke(_COMPACT_PROMPT.format(history=history_text))
            self._summary_cache = getattr(response, "content", None) or str(response)
            logger.debug(
                "Compacted %d messages into summary (%d chars)",
                len(overflow),
                len(self._summary_cache),
            )
        except Exception:
            logger.warning("Memory compaction failed — continuing with window only", exc_info=True)
