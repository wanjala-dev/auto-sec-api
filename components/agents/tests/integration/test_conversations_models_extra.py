"""Additional tests for conversation models."""

import pytest

from infrastructure.persistence.ai.conversations.models import Conversation, ConversationMessage

pytestmark = pytest.mark.django_db


def test_conversation_pdf_id_property_round_trip(user_factory):
    convo = Conversation.objects.create(user=user_factory(), title="Doc chat")
    convo.pdf_id = "123"
    convo.save()

    convo.refresh_from_db()
    assert convo.metadata["pdf_id"] == "123"
    assert convo.pdf_id == "123"


def test_conversation_str_falls_back_to_untitled(user_factory):
    convo = Conversation.objects.create(user=user_factory(), title="")
    assert "Untitled" in str(convo)


def test_message_str_truncates_content(conversation_factory):
    convo = conversation_factory()
    msg = ConversationMessage.objects.create(
        conversation=convo,
        role="assistant",
        content="a" * 100,
    )
    assert "assistant:" in str(msg)
