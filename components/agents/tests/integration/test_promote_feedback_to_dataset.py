"""Integration tests for the Wave-4 feedback → eval-dataset bridge."""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command


def _seed_thumbs_down(*, workspace_owner, conversation_metadata=None):
    """Create a Conversation with a human → assistant pair + thumbs-down."""
    from infrastructure.persistence.ai.conversations.models import (
        AgentResponseFeedback,
        Conversation,
        ConversationMessage,
    )

    conversation = Conversation.objects.create(
        user=workspace_owner,
        metadata=conversation_metadata or {},
    )
    human = ConversationMessage.objects.create(
        conversation=conversation,
        role="human",
        content="show me grants closing this month",
    )
    assistant = ConversationMessage.objects.create(
        conversation=conversation,
        role="assistant",
        content="(planner output that was wrong)",
    )
    feedback = AgentResponseFeedback.objects.create(
        message=assistant,
        user=workspace_owner,
        rating=AgentResponseFeedback.RATING_DOWN,
        comment="the dates were wrong",
    )
    return conversation, human, assistant, feedback


@pytest.mark.django_db
class TestPromoteFeedbackToDataset:
    def test_appends_thumbs_down_to_new_dataset(self, tmp_path, user_factory):
        owner = user_factory()
        _seed_thumbs_down(workspace_owner=owner)

        dataset_path = tmp_path / "from_feedback.json"
        out = StringIO()
        call_command(
            "promote_feedback_to_dataset",
            "--dataset", "from_feedback",
            "--dataset-path", str(dataset_path),
            stdout=out,
        )
        data = json.loads(dataset_path.read_text())
        assert len(data["cases"]) == 1
        case = data["cases"][0]
        assert case["id"].startswith("feedback-")
        assert case["goal"] == "show me grants closing this month"
        assert case["feedback"]["rating"] == "down"
        assert case["feedback"]["comment"] == "the dates were wrong"
        assert "Appended 1 case(s)" in out.getvalue()

    def test_idempotent_on_rerun(self, tmp_path, user_factory):
        owner = user_factory()
        _seed_thumbs_down(workspace_owner=owner)

        dataset_path = tmp_path / "from_feedback.json"
        for _ in range(2):
            call_command(
                "promote_feedback_to_dataset",
                "--dataset", "from_feedback",
                "--dataset-path", str(dataset_path),
                stdout=StringIO(),
            )

        data = json.loads(dataset_path.read_text())
        assert len(data["cases"]) == 1, "second run should be a no-op"

    def test_dry_run_does_not_write(self, tmp_path, user_factory):
        owner = user_factory()
        _seed_thumbs_down(workspace_owner=owner)

        dataset_path = tmp_path / "from_feedback.json"
        out = StringIO()
        call_command(
            "promote_feedback_to_dataset",
            "--dataset", "from_feedback",
            "--dataset-path", str(dataset_path),
            "--dry-run",
            stdout=out,
        )
        assert not dataset_path.exists()
        assert "Would append 1 case(s)" in out.getvalue()

    def test_skips_thumbs_up(self, tmp_path, user_factory):
        from infrastructure.persistence.ai.conversations.models import (
            AgentResponseFeedback,
            Conversation,
            ConversationMessage,
        )

        owner = user_factory()
        conversation = Conversation.objects.create(user=owner)
        assistant = ConversationMessage.objects.create(
            conversation=conversation, role="assistant", content="great answer",
        )
        AgentResponseFeedback.objects.create(
            message=assistant, user=owner,
            rating=AgentResponseFeedback.RATING_UP,
        )

        dataset_path = tmp_path / "from_feedback.json"
        call_command(
            "promote_feedback_to_dataset",
            "--dataset", "from_feedback",
            "--dataset-path", str(dataset_path),
            stdout=StringIO(),
        )
        # Thumbs-up is not a failure case — must not appear.
        if dataset_path.exists():
            data = json.loads(dataset_path.read_text())
            assert data["cases"] == []
