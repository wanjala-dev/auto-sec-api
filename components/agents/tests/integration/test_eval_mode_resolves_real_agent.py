"""An evaluation runs as the workspace's OWN agent (ADR 0033).

Two failures in a row got the system here, and the second is the one that
matters. The eval runner minted a fresh UUID for `agent_id`:

  1. With an `eval-` prefix it was not a UUID at all — every case died on
     "is not a valid UUID", the run completed in seconds at $0.00, and no
     DeepRun provenance was recorded.
  2. With the prefix removed it was a valid UUID naming no row — every case
     died on "Agent matching query does not exist".

Fixing (1) without (2) is why this file exists. The format was never the real
problem: `agent_id` is the primary key of a real `Agent` row, and a synthetic
one would have evaluated a memory-less agent no customer runs. An eval that
scores a different agent than the one in production is not measuring anything a
buyer cares about.
"""

from __future__ import annotations

import pytest

from components.agents.application.providers.agent_registry_provider import (
    AgentRegistryProvider,
)
from infrastructure.persistence.ai.agents.models import Agent

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _agent(workspace, user, agent_type="triage_agent"):
    return Agent.objects.create(agent_type=agent_type, user=user, workspace=workspace)


class TestItFindsTheWorkspacesOwnAgent:
    def test_it_returns_the_agent_for_that_workspace_and_type(self, workspace_factory, user_factory):
        workspace, user = workspace_factory(), user_factory()
        agent = _agent(workspace, user)

        resolved = AgentRegistryProvider._resolve_agent_id(agent_type="triage_agent", workspace_id=workspace.id)

        assert resolved == str(agent.agent_id)

    def test_another_tenants_agent_is_never_returned(self, workspace_factory, user_factory):
        """Evaluating another tenant's agent would be a cross-tenant read, and
        on the pooled tier this filter IS the boundary."""
        mine, theirs, user = workspace_factory(), workspace_factory(), user_factory()
        _agent(theirs, user)

        assert AgentRegistryProvider._resolve_agent_id(agent_type="triage_agent", workspace_id=mine.id) is None

    def test_a_different_agent_type_is_not_substituted(self, workspace_factory, user_factory):
        """Silently running a different agent would report a score against the
        wrong subject entirely."""
        workspace, user = workspace_factory(), user_factory()
        _agent(workspace, user, agent_type="triage_agent")

        assert (
            AgentRegistryProvider._resolve_agent_id(agent_type="optimization_agent", workspace_id=workspace.id) is None
        )

    def test_repeated_resolution_picks_the_same_agent(self, workspace_factory, user_factory):
        """An eval whose subject changes between runs is not a comparison — and
        comparing runs is the entire point of a fixed suite."""
        workspace, user = workspace_factory(), user_factory()
        _agent(workspace, user)
        _agent(workspace, user)

        first = AgentRegistryProvider._resolve_agent_id(agent_type="triage_agent", workspace_id=workspace.id)
        second = AgentRegistryProvider._resolve_agent_id(agent_type="triage_agent", workspace_id=workspace.id)

        assert first == second


class TestNoAgentIsStatedNotGuessed:
    def test_a_workspace_with_no_such_agent_refuses_with_a_readable_reason(self, workspace_factory, user_factory):
        """It must not fall back to any agent it can find. "Nothing to evaluate"
        is a true and actionable answer; a score against a substituted agent is
        neither."""
        workspace = workspace_factory()

        result = AgentRegistryProvider().run_in_evaluation_mode(
            agent_type="triage_agent",
            user_id=user_factory().id,
            workspace_id=workspace.id,
            model_slug="gpt-4o-mini",
            query="anything",
        )

        assert result["success"] is False
        assert "no 'triage_agent' agent to evaluate" in result["error"]
