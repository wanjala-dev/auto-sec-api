"""SQL Memory Builder for conversation history.

LangChain 1.x migration (2026-07-19): ``ConversationBufferMemory`` was removed
in 1.x. The builders now return the native ``SqlConversationMemory`` loader —
see ``memories/conversation_memory.py`` for the design (SQL-history threading
into the ``create_agent`` graph input; persistence stays in memory_service).
Builder signatures are unchanged so ``memory_service.get_memory`` keeps working.
"""

from langchain_core.messages import SystemMessage

from .conversation_memory import SqlConversationMemory
from .histories.sql_history import SqlMessageHistory


def build_memory(chat_args, max_messages=None, max_message_chars=None, max_total_chars=None):
    """Build full-buffer conversation memory with SQL history.

    Args:
        chat_args: Chat configuration object with conversation_id

    Returns:
        SqlConversationMemory instance
    """
    return SqlConversationMemory(
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
    )


def build_memory_with_system_message(
    chat_args,
    system_message="You are a helpful AI assistant.",
    max_messages=None,
    max_message_chars=None,
    max_total_chars=None,
):
    """Build conversation memory seeded with a persisted system message.

    Args:
        chat_args: Chat configuration object with conversation_id
        system_message: System message to include

    Returns:
        SqlConversationMemory instance with system message persisted
    """
    memory = build_memory(
        chat_args,
        max_messages=max_messages,
        max_message_chars=max_message_chars,
        max_total_chars=max_total_chars,
    )

    if system_message:
        memory.chat_memory.add_message(SystemMessage(content=system_message))

    return memory
