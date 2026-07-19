"""Compacting memory — summarizes old messages instead of dropping them.

When conversation history exceeds the window size, older messages are
summarized into a single "memory summary" message that preserves context
without consuming the full token budget.

This replaces the hard-truncation behaviour of ConversationBufferWindowMemory.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.memory import ConversationBufferWindowMemory
from langchain.schema import BaseMessage, SystemMessage

from .histories.sql_history import SqlMessageHistory

logger = logging.getLogger(__name__)

_COMPACT_PROMPT = (
    "Summarize the following conversation history into a concise paragraph. "
    "Preserve key facts, decisions, action items, and user preferences. "
    "Omit greetings, filler, and repetition.\n\n"
    "{history}"
)


class CompactingMemory(ConversationBufferWindowMemory):
    """Window memory that compacts overflow messages into a summary.

    When messages exceed ``k`` exchanges:
    1. The oldest messages beyond the window are collected.
    2. An LLM summarizes them into a single system message.
    3. The summary is prepended to the window so context is preserved.

    If no LLM is provided, falls back to simple truncation (same as base).
    """

    compaction_llm: Any = None  # LangChain BaseChatModel or BaseLLM
    _summary_cache: str = ""

    class Config:
        arbitrary_types_allowed = True

    @property
    def buffer_as_messages(self) -> list[BaseMessage]:
        """Override to prepend compacted summary if available."""
        messages = super().buffer_as_messages
        if self._summary_cache:
            summary_msg = SystemMessage(
                content=f"[Conversation summary from earlier messages]\n{self._summary_cache}"
            )
            return [summary_msg, *list(messages)]
        return messages

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, str]) -> None:
        """Save new exchange and compact overflow if needed."""
        # Get messages before save to check overflow
        pre_count = len(self.chat_memory.messages) if hasattr(self.chat_memory, "messages") else 0

        super().save_context(inputs, outputs)

        # Check if we dropped messages (window overflow)
        post_count = len(self.chat_memory.messages) if hasattr(self.chat_memory, "messages") else 0

        if pre_count > 0 and post_count < pre_count and self.compaction_llm is not None:
            self._compact_overflow()

    def _compact_overflow(self) -> None:
        """Summarize dropped messages into a running summary."""
        try:
            all_messages = self.chat_memory.messages
            # The window keeps the last k*2 messages; everything else was dropped
            # We only have access to what's in the window, so we compact
            # the existing summary + oldest window messages
            if len(all_messages) < 2:
                return

            # Take the oldest half of the window for compaction
            midpoint = max(len(all_messages) // 2, 1)
            to_compact = all_messages[:midpoint]

            history_text = "\n".join(
                f"{msg.type}: {msg.content[:500]}" for msg in to_compact
            )
            if self._summary_cache:
                history_text = f"Previous summary: {self._summary_cache}\n\n{history_text}"

            prompt = _COMPACT_PROMPT.format(history=history_text)
            response = self.compaction_llm.invoke(prompt)

            if hasattr(response, "content"):
                self._summary_cache = response.content
            else:
                self._summary_cache = str(response)

            logger.debug("Compacted %d messages into summary (%d chars)", midpoint, len(self._summary_cache))
        except Exception:
            logger.warning("Memory compaction failed — continuing with window only", exc_info=True)


def compacting_memory_builder(
    chat_args,
    *,
    k: int = 5,
    compaction_llm=None,
    max_messages: int | None = None,
    max_message_chars: int | None = None,
    max_total_chars: int | None = None,
) -> CompactingMemory:
    """Build a compacting memory instance backed by SQL history."""
    return CompactingMemory(
        memory_key="chat_history",
        output_key="output",
        return_messages=True,
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
        k=k,
        compaction_llm=compaction_llm,
    )
