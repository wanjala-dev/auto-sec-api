"""Tests for SQL message history limits."""
import pytest

from components.agents.infrastructure.adapters.langchain.memories.histories.sql_history import SqlMessageHistory


@pytest.mark.django_db
def test_sql_history_limits_messages_and_truncates(conversation_factory, conversation_message_factory):
    conversation = conversation_factory()
    conversation_message_factory(conversation=conversation, role="human", content="alpha-one")
    conversation_message_factory(conversation=conversation, role="assistant", content="beta-two")
    conversation_message_factory(conversation=conversation, role="human", content="gamma-three")

    history = SqlMessageHistory(
        conversation_id=str(conversation.id),
        max_messages=2,
        max_message_chars=5,
    )

    messages = history.messages

    assert len(messages) == 2
    assert messages[0].content.startswith("beta")
    assert messages[1].content.startswith("gamma")
