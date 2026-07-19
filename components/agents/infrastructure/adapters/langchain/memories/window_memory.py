"""Window Memory Builder for conversation history.

LangChain 1.x migration (2026-07-19): ``ConversationBufferWindowMemory`` was
removed in 1.x. The builders now return the native ``SqlWindowConversationMemory``
loader (last ``k`` exchanges = 2·k messages) — see
``memories/conversation_memory.py``. Builder signatures are unchanged so
``memory_service.get_memory`` keeps working.
"""

from .conversation_memory import SqlWindowConversationMemory
from .histories.sql_history import SqlMessageHistory


def window_buffer_memory_builder(chat_args, max_messages=None, max_message_chars=None, max_total_chars=None):
    """Build window memory with SQL history (default window: last 2 exchanges).

    Args:
        chat_args: Chat configuration object with conversation_id

    Returns:
        SqlWindowConversationMemory instance
    """
    return window_buffer_memory_builder_with_k(
        chat_args,
        k=2,
        max_messages=max_messages,
        max_message_chars=max_message_chars,
        max_total_chars=max_total_chars,
    )


def window_buffer_memory_builder_with_k(
    chat_args, k=2, max_messages=None, max_message_chars=None, max_total_chars=None
):
    """Build window memory with custom window size.

    Args:
        chat_args: Chat configuration object with conversation_id
        k: Number of exchanges to keep in memory

    Returns:
        SqlWindowConversationMemory instance
    """
    return SqlWindowConversationMemory(
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
        k=k,
    )
