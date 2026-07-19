"""Unit tests for ExecutionFeedbackEntity."""

import pytest
from uuid import uuid4

from components.agents.domain.entities.execution_feedback_entity import (
    ExecutionFeedbackEntity,
    FeedbackSignal,
)


class TestExecutionFeedbackEntity:
    def test_create_thumbs_up(self):
        feedback = ExecutionFeedbackEntity.create(
            execution_id=42,
            user_id=uuid4(),
            signal=FeedbackSignal.THUMBS_UP,
            comment="Very helpful!",
            tags=["helpful", "accurate"],
        )
        assert feedback.is_positive
        assert not feedback.is_negative
        assert feedback.signal == FeedbackSignal.THUMBS_UP
        assert feedback.comment == "Very helpful!"
        assert "helpful" in feedback.tags

    def test_create_thumbs_down(self):
        feedback = ExecutionFeedbackEntity.create(
            execution_id=43,
            user_id=uuid4(),
            signal=FeedbackSignal.THUMBS_DOWN,
        )
        assert feedback.is_negative
        assert not feedback.is_positive

    def test_invalid_signal_raises(self):
        with pytest.raises(ValueError, match="Invalid feedback signal"):
            ExecutionFeedbackEntity.create(
                execution_id=1,
                user_id=uuid4(),
                signal="invalid",
            )
