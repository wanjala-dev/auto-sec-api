"""
SQL Memory Builder for conversation history
"""
from langchain.memory import ConversationBufferMemory
from .histories.sql_history import SqlMessageHistory


def build_memory(chat_args, max_messages=None, max_message_chars=None, max_total_chars=None):
    """
    Build conversation buffer memory with SQL history
    
    Args:
        chat_args: Chat configuration object with conversation_id
    
    Returns:
        ConversationBufferMemory instance
    """
    return ConversationBufferMemory(
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
        return_messages=True,
        memory_key="chat_history",
        output_key="output"
    )


def build_memory_with_system_message(
    chat_args,
    system_message="You are a helpful AI assistant.",
    max_messages=None,
    max_message_chars=None,
    max_total_chars=None,
):
    """
    Build conversation buffer memory with system message
    
    Args:
        chat_args: Chat configuration object with conversation_id
        system_message: System message to include
    
    Returns:
        ConversationBufferMemory instance with system message
    """
    memory = ConversationBufferMemory(
        chat_memory=SqlMessageHistory(
            conversation_id=chat_args.conversation_id,
            max_messages=max_messages,
            max_message_chars=max_message_chars,
            max_total_chars=max_total_chars,
        ),
        return_messages=True,
        memory_key="chat_history",
        output_key="output"
    )
    
    # Add system message if provided
    if system_message:
        from langchain.schema import SystemMessage
        memory.chat_memory.add_message(SystemMessage(content=system_message))
    
    return memory














