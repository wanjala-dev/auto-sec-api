"""Unit tests for ConversationEntity and ConversationMessageEntity."""

from datetime import datetime
from uuid import uuid4

from components.agents.domain.entities.conversation_entity import (
    ConversationEntity,
    ConversationMessageEntity,
)


class TestConversationEntity:
    """Tests for ConversationEntity — AI conversations."""

    def test_create_minimal_conversation(self):
        """Test creating a conversation with minimal required fields."""
        conv_id = uuid4()
        title = "Budget Analysis Discussion"

        conversation = ConversationEntity(
            id=conv_id,
            title=title,
        )

        assert conversation.id == conv_id
        assert conversation.title == title
        assert conversation.is_active is True
        assert conversation.user_id is None
        assert conversation.metadata == {}
        assert conversation.created_at is None
        assert conversation.updated_at is None

    def test_create_conversation_with_all_fields(self):
        """Test creating a conversation with all fields populated."""
        conv_id = uuid4()
        user_id = uuid4()
        now = datetime.utcnow()
        metadata = {
            "pdf_id": "pdf_123abc",
            "agent_type": "budget_analyst",
            "department": "Finance",
            "tags": ["budget", "q1-2025"],
        }

        conversation = ConversationEntity(
            id=conv_id,
            title="Q1 Budget Review",
            is_active=True,
            user_id=user_id,
            metadata=metadata,
            created_at=now,
            updated_at=now,
        )

        assert conversation.id == conv_id
        assert conversation.title == "Q1 Budget Review"
        assert conversation.is_active is True
        assert conversation.user_id == user_id
        assert conversation.metadata == metadata
        assert conversation.created_at == now
        assert conversation.updated_at == now

    def test_conversation_is_frozen(self):
        """Test that ConversationEntity is immutable."""
        conversation = ConversationEntity(
            id=uuid4(),
            title="Test",
        )

        try:
            conversation.is_active = False
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected

    def test_conversation_active_inactive(self):
        """Test active and inactive conversations."""
        active_conv = ConversationEntity(
            id=uuid4(),
            title="Active Discussion",
            is_active=True,
        )

        inactive_conv = ConversationEntity(
            id=uuid4(),
            title="Archived Discussion",
            is_active=False,
        )

        assert active_conv.is_active is True
        assert inactive_conv.is_active is False

    def test_conversation_pdf_id_property(self):
        """Test pdf_id property extraction from metadata."""
        pdf_id = "pdf_xyz_789"
        metadata = {"pdf_id": pdf_id, "other_key": "value"}

        conversation = ConversationEntity(
            id=uuid4(),
            title="PDF Discussion",
            metadata=metadata,
        )

        assert conversation.pdf_id == pdf_id

    def test_conversation_pdf_id_when_not_present(self):
        """Test pdf_id property when metadata doesn't have it."""
        conversation = ConversationEntity(
            id=uuid4(),
            title="No PDF",
            metadata={"agent_type": "budget_analyst"},
        )

        assert conversation.pdf_id is None

    def test_conversation_pdf_id_with_empty_metadata(self):
        """Test pdf_id property with empty metadata."""
        conversation = ConversationEntity(
            id=uuid4(),
            title="Empty metadata",
            metadata={},
        )

        assert conversation.pdf_id is None

    def test_conversation_with_complex_metadata(self):
        """Test conversation with nested metadata."""
        metadata = {
            "pdf_id": "pdf_budget_2025",
            "agent": {
                "type": "budget_analyst",
                "instance_id": "agent_456",
            },
            "context": {
                "department": "Finance",
                "fiscal_year": 2025,
                "approvers": ["manager", "director"],
            },
            "tags": ["budget", "finance", "q1"],
        }

        conversation = ConversationEntity(
            id=uuid4(),
            title="Complex Metadata Discussion",
            metadata=metadata,
        )

        assert conversation.metadata == metadata
        assert conversation.metadata["agent"]["type"] == "budget_analyst"
        assert conversation.metadata["context"]["fiscal_year"] == 2025
        assert len(conversation.metadata["tags"]) == 3

    def test_conversation_with_user(self):
        """Test conversation associated with a user."""
        user_id = uuid4()

        conversation = ConversationEntity(
            id=uuid4(),
            title="User-specific discussion",
            user_id=user_id,
        )

        assert conversation.user_id == user_id

    def test_conversation_timestamps(self):
        """Test conversation timestamps."""
        created_at = datetime(2025, 1, 1, 10, 0, 0)
        updated_at = datetime(2025, 1, 5, 14, 30, 0)

        conversation = ConversationEntity(
            id=uuid4(),
            title="Timestamped Conversation",
            created_at=created_at,
            updated_at=updated_at,
        )

        assert conversation.created_at == created_at
        assert conversation.updated_at == updated_at
        assert conversation.updated_at > conversation.created_at

    def test_conversation_title_variations(self):
        """Test conversations with different title styles."""
        short_title = ConversationEntity(
            id=uuid4(),
            title="Q1",
        )

        long_title = ConversationEntity(
            id=uuid4(),
            title="A very long conversation title about quarterly budget planning and financial forecasting for 2025",
        )

        special_chars_title = ConversationEntity(
            id=uuid4(),
            title="Q1 2025 Budget - Review & Approval (Final) [Draft]",
        )

        assert len(short_title.title) == 2
        assert len(long_title.title) > 80
        assert "Q1" in short_title.title
        assert "&" in special_chars_title.title


class TestConversationMessageEntity:
    """Tests for ConversationMessageEntity — messages in conversations."""

    def test_create_minimal_message(self):
        """Test creating a message with minimal required fields."""
        msg_id = uuid4()
        conv_id = uuid4()

        message = ConversationMessageEntity(
            id=msg_id,
            conversation_id=conv_id,
            role="user",
            content="What is the Q1 budget?",
        )

        assert message.id == msg_id
        assert message.conversation_id == conv_id
        assert message.role == "user"
        assert message.content == "What is the Q1 budget?"
        assert message.metadata == {}
        assert message.created_at is None

    def test_create_message_with_all_fields(self):
        """Test creating a message with all fields populated."""
        msg_id = uuid4()
        conv_id = uuid4()
        now = datetime.utcnow()
        metadata = {
            "tokens_used": 150,
            "model": "gpt-4",
            "latency_ms": 2500,
        }

        message = ConversationMessageEntity(
            id=msg_id,
            conversation_id=conv_id,
            role="assistant",
            content="The Q1 budget is $500,000.",
            metadata=metadata,
            created_at=now,
        )

        assert message.id == msg_id
        assert message.conversation_id == conv_id
        assert message.role == "assistant"
        assert message.content == "The Q1 budget is $500,000."
        assert message.metadata == metadata
        assert message.created_at == now

    def test_message_is_frozen(self):
        """Test that ConversationMessageEntity is immutable."""
        message = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=uuid4(),
            role="user",
            content="Test",
        )

        try:
            message.content = "Modified"
            assert False, "Should not be able to modify frozen dataclass"
        except (AttributeError, TypeError):
            pass  # Expected

    def test_message_roles(self):
        """Test messages with different roles."""
        conv_id = uuid4()

        human_msg = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=conv_id,
            role="human",
            content="User question",
        )

        assistant_msg = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=conv_id,
            role="assistant",
            content="Assistant response",
        )

        system_msg = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=conv_id,
            role="system",
            content="System instruction",
        )

        assert human_msg.role == "human"
        assert assistant_msg.role == "assistant"
        assert system_msg.role == "system"

    def test_message_in_conversation(self):
        """Test messages associated with a conversation."""
        conv_id = uuid4()

        msg1 = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=conv_id,
            role="human",
            content="Question 1",
        )

        msg2 = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=conv_id,
            role="assistant",
            content="Answer 1",
        )

        assert msg1.conversation_id == conv_id
        assert msg2.conversation_id == conv_id
        assert msg1.conversation_id == msg2.conversation_id

    def test_message_with_long_content(self):
        """Test message with long content."""
        long_content = "A" * 10000

        message = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=uuid4(),
            role="assistant",
            content=long_content,
        )

        assert len(message.content) == 10000
        assert message.content == long_content

    def test_message_with_metadata(self):
        """Test message with metadata."""
        metadata = {
            "tokens_used": {
                "prompt": 100,
                "completion": 50,
                "total": 150,
            },
            "model": "gpt-4o",
            "temperature": 0.7,
            "top_p": 0.9,
            "latency_ms": 2500,
            "cost_usd": 0.005,
        }

        message = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=uuid4(),
            role="assistant",
            content="Response",
            metadata=metadata,
        )

        assert message.metadata == metadata
        assert message.metadata["tokens_used"]["total"] == 150
        assert message.metadata["model"] == "gpt-4o"
        assert message.metadata["cost_usd"] == 0.005

    def test_message_timestamp(self):
        """Test message creation timestamp."""
        created_at = datetime(2025, 1, 15, 14, 30, 45)

        message = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=uuid4(),
            role="user",
            content="Message",
            created_at=created_at,
        )

        assert message.created_at == created_at

    def test_conversation_flow(self):
        """Test a conversation with multiple messages."""
        conv_id = uuid4()
        created_at_1 = datetime(2025, 1, 15, 14, 0, 0)
        created_at_2 = datetime(2025, 1, 15, 14, 1, 0)
        created_at_3 = datetime(2025, 1, 15, 14, 2, 0)

        messages = [
            ConversationMessageEntity(
                id=uuid4(),
                conversation_id=conv_id,
                role="human",
                content="What's the budget status?",
                created_at=created_at_1,
            ),
            ConversationMessageEntity(
                id=uuid4(),
                conversation_id=conv_id,
                role="assistant",
                content="The Q1 budget is on track at 78% spent.",
                created_at=created_at_2,
            ),
            ConversationMessageEntity(
                id=uuid4(),
                conversation_id=conv_id,
                role="human",
                content="What about Q2?",
                created_at=created_at_3,
            ),
        ]

        assert len(messages) == 3
        assert all(m.conversation_id == conv_id for m in messages)
        assert messages[0].role == "human"
        assert messages[1].role == "assistant"
        assert messages[2].role == "human"
        assert messages[0].created_at < messages[1].created_at < messages[2].created_at

    def test_message_with_special_characters(self):
        """Test message with special characters and formatting."""
        content = """
        Budget Analysis:
        - Q1: $500,000 (100%)
        - Q2: $520,000 (104%)
        - Q3: $480,000 (96%)

        Status: "On Track" ✓
        Notes: Impact < 5% → OK
        """

        message = ConversationMessageEntity(
            id=uuid4(),
            conversation_id=uuid4(),
            role="assistant",
            content=content,
        )

        assert message.content == content
        assert "Q1" in message.content
        assert "$500,000" in message.content
        assert "✓" in message.content
