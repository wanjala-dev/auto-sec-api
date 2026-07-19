import pytest

from infrastructure.persistence.ai.agents.models import Agent, AgentExecution


pytestmark = pytest.mark.django_db


URL = "/ai/agents/graph/"


def test_agent_graph_returns_agent_types_sessions_and_activity(
    api_client, workspace_factory, user_factory,
):
    """The graph endpoint returns agent-level metadata only.

    Phase 5 of the Agents-as-Teammates migration dropped the ``actions``
    + ``action_counts`` fields — findings are Kanban tasks now, read via
    ``/ai/findings/``.
    """
    workspace = workspace_factory(ai_teammate_enabled=True)
    user = workspace.workspace_owner or user_factory()
    api_client.force_authenticate(user=user)

    agent = Agent.objects.create(
        agent_type="financial_agent",
        user=user,
        workspace=workspace,
        status="active",
    )
    AgentExecution.objects.create(
        agent=agent,
        query="test run",
        status=AgentExecution.STATUS_RUNNING,
        progress=72,
    )
    AgentExecution.objects.create(
        agent=agent,
        query="completed run",
        status=AgentExecution.STATUS_COMPLETED,
        progress=100,
    )

    response = api_client.get(URL, {"workspace_id": str(workspace.id)})

    assert response.status_code == 200
    data = response.data
    assert data["agent_types"]
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["status"] == AgentExecution.STATUS_RUNNING
    assert data["sessions"][0]["progress"] == 72
    assert "financial_agent" in data["active_agent_types"]
    assert any(
        row["agent_type"] == "financial_agent" and row["active"] == 1
        for row in data["agent_type_activity"]
    )
    # Phase 5 dropped these fields entirely.
    assert "actions" not in data
    assert "action_counts" not in data
    assert "pagination" not in data
