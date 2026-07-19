"""
Window Memory Builder for conversation history
"""
from langchain.memory import ConversationBufferWindowMemory
from .histories.sql_history import SqlMessageHistory


def window_buffer_memory_builder(chat_args, max_messages=None, max_message_chars=None, max_total_chars=None):
    """
    Build window buffer memory with SQL history
    
    Args:
        chat_args: Chat configuration object with conversation_id
    
    Returns:
        ConversationBufferWindowMemory instance
    """
    return ConversationBufferWindowMemory(
        memory_key="chat_history",
        output_key="output",
        return_messages=True,
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
        k=2  # Keep last 2 exchanges
    )


def window_buffer_memory_builder_with_k(chat_args, k=2, max_messages=None, max_message_chars=None, max_total_chars=None):
    """
    Build window buffer memory with custom window size
    
    Args:
        chat_args: Chat configuration object with conversation_id
        k: Number of exchanges to keep in memory
    
    Returns:
        ConversationBufferWindowMemory instance
    """
    return ConversationBufferWindowMemory(
        memory_key="chat_history",
        output_key="output",
        return_messages=True,
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
        k=k
    )







































