"""Tests for agent memory pagination helpers."""
from datetime import timedelta

import pytest
from django.utils import timezone

from components.agents.infrastructure.adapters.langchain.memory_service import AgentMemoryService
from infrastructure.persistence.ai.agents.models import Agent


@pytest.mark.django_db
def test_conversation_history_paginates(
    user_factory,
    workspace_factory,
    conversation_factory,
    conversation_message_factory,
):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    conversation = conversation_factory(user=user)
    agent = Agent.objects.create(
        agent_type="sponsorship_agent",
        user=user,
        workspace=workspace,
        status="active",
        config={"conversation_id": str(conversation.id)},
    )

    base_time = timezone.now()
    for idx in range(5):
        conversation_message_factory(
            conversation=conversation,
            content=f"msg {idx}",
            created_at=base_time + timedelta(seconds=idx),
        )

    service = AgentMemoryService(str(agent.agent_id))

    history = service.get_conversation_history(limit=2, offset=1, order="asc")
    assert [item["content"] for item in history] == ["msg 1", "msg 2"]

    history_desc = service.get_conversation_history(limit=2, offset=0, order="desc")
    assert [item["content"] for item in history_desc] == ["msg 4", "msg 3"]
