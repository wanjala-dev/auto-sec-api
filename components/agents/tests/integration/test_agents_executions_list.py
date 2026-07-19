"""Tests for paginated agent execution listings."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from infrastructure.persistence.ai.agents.models import Agent, AgentExecution


@pytest.mark.django_db
def test_list_agent_executions_paginates(api_client, user_factory, workspace_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    agent = Agent.objects.create(
        agent_type="sponsorship_agent",
        user=user,
        workspace=workspace,
        status="active",
        config={},
    )

    base_time = timezone.now()
    executions = []
    for idx in range(3):
        execution = AgentExecution.objects.create(
            agent=agent,
            query=f"q{idx}",
            result=f"r{idx}",
            status=AgentExecution.STATUS_COMPLETED,
            success=True,
            progress=100,
        )
        execution.created_at = base_time + timedelta(seconds=idx)
        execution.save(update_fields=["created_at"])
        executions.append(execution)

    api_client.force_authenticate(user=user)
    url = reverse("agents:agent-executions", args=[str(agent.agent_id)])
    response = api_client.get(url, {"limit": 2, "offset": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["total"] == 3
    assert payload["pagination"]["returned"] == 2
    assert [item["query"] for item in payload["executions"]] == ["q1", "q0"]
