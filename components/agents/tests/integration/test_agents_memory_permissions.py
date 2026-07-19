"""Tests for agent memory access control."""
import pytest
from django.urls import reverse

from infrastructure.persistence.ai.agents.models import Agent


@pytest.mark.django_db
def test_get_agent_memory_allows_followers(
    api_client,
    user_factory,
    workspace_factory,
    conversation_factory,
    conversation_message_factory,
):
    owner = user_factory()
    follower = user_factory()
    workspace = workspace_factory(owner=owner)
    workspace.followers.add(follower)

    conversation = conversation_factory(user=owner, metadata={'workspace_id': str(workspace.id)})
    conversation_message_factory(conversation=conversation, content="hello world")

    agent = Agent.objects.create(
        agent_type="sponsorship_agent",
        user=owner,
        workspace=workspace,
        status="active",
        config={"conversation_id": str(conversation.id)},
    )

    api_client.force_authenticate(user=follower)
    url = reverse("agents:agent-memory", args=[str(agent.agent_id)])
    response = api_client.get(url, {"limit": 10, "order": "asc"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_history"][0]["content"] == "hello world"
