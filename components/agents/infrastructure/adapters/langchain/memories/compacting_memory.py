"""Compacting memory — summarizes old messages instead of dropping them.

When conversation history exceeds the window size, older messages are
summarized into a single "memory summary" message that preserves context
without consuming the full token budget.

LangChain 1.x migration (2026-07-19): the 0.3 implementation subclassed
``ConversationBufferWindowMemory`` (removed in 1.x) and compacted on
``save_context`` (a hook that no longer exists — persistence moved to
``memory_service.record_execution``). The native
``CompactingConversationMemory`` compacts on **load** instead: overflow
beyond the window is summarised into one system message prepended to the
window each time the agent threads history into the graph. Same behaviour
surface (LLM summary, truncation fallback), no LangChain memory classes.
"""

from __future__ import annotations

from .conversation_memory import CompactingConversationMemory
from .histories.sql_history import SqlMessageHistory

# Re-export under the historical name so existing imports keep working.
CompactingMemory = CompactingConversationMemory


def compacting_memory_builder(
    chat_args,
    *,
    k: int = 5,
    compaction_llm=None,
    max_messages: int | None = None,
    max_message_chars: int | None = None,
    max_total_chars: int | None = None,
) -> CompactingConversationMemory:
    """Build a compacting memory instance backed by SQL history."""
    return CompactingConversationMemory(
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
        k=k,
        compaction_llm=compaction_llm,
    )
