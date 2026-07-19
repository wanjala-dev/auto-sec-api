"""Integration tests — agent capability toggles + draft_pr serializer surface.

The capabilities patch is the API half of the risk gate: only allowlisted keys,
values coerced to bool, merged into ``Agent.config.capabilities``.
"""

from __future__ import annotations

import pytest

from components.agents.application.ports.agent_profile_port import PatchAgentCapabilitiesCommand
from components.agents.application.service import AgentsService


def _agent_row(workspace):
    from infrastructure.persistence.ai.agents.models import Agent

    return Agent.objects.create(
        workspace=workspace,
        user=workspace.workspace_owner,
        agent_type="triage_agent",
        config={},
    )


@pytest.mark.django_db
class TestPatchAgentCapabilities:
    def test_enables_allowlisted_capability(self, workspace_factory):
        agent = _agent_row(workspace_factory())
        result = AgentsService().patch_agent_capabilities(
            PatchAgentCapabilitiesCommand(agent_id=str(agent.agent_id), data={"open_draft_pr": True})
        )
        assert result.capabilities == {"open_draft_pr": True}
        agent.refresh_from_db()
        assert agent.config["capabilities"]["open_draft_pr"] is True

    def test_disables_and_coerces_bool(self, workspace_factory):
        agent = _agent_row(workspace_factory())
        AgentsService().patch_agent_capabilities(
            PatchAgentCapabilitiesCommand(agent_id=str(agent.agent_id), data={"open_draft_pr": True})
        )
        result = AgentsService().patch_agent_capabilities(
            PatchAgentCapabilitiesCommand(agent_id=str(agent.agent_id), data={"open_draft_pr": 0})
        )
        assert result.capabilities["open_draft_pr"] is False

    def test_unknown_capability_rejected(self, workspace_factory):
        from components.agents.domain.errors import AgentEngagementError

        agent = _agent_row(workspace_factory())
        with pytest.raises(AgentEngagementError):
            AgentsService().patch_agent_capabilities(
                PatchAgentCapabilitiesCommand(agent_id=str(agent.agent_id), data={"delete_everything": True})
            )
        agent.refresh_from_db()
        assert (agent.config or {}).get("capabilities") in (None, {})

    def test_merge_preserves_other_config(self, workspace_factory):
        agent = _agent_row(workspace_factory())
        agent.config = {"custom_profile": {"tone": "calm"}}
        agent.save(update_fields=["config"])
        AgentsService().patch_agent_capabilities(
            PatchAgentCapabilitiesCommand(agent_id=str(agent.agent_id), data={"open_draft_pr": True})
        )
        agent.refresh_from_db()
        assert agent.config["custom_profile"] == {"tone": "calm"}
        assert agent.config["capabilities"] == {"open_draft_pr": True}


@pytest.mark.django_db
class TestDraftPrSerializerSurface:
    def test_log_watch_carries_draft_pr(self, workspace_factory, team_factory):
        from components.project.mappers.rest.project_serializers import TaskSerializer
        from infrastructure.persistence.project.models import Column, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        column = Column.objects.create(
            team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
        )
        pr = {"url": "https://github.com/x/y/pull/1", "repo": "x/y", "branch": "autosec/finding-1"}
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            column=column,
            created_by=owner,
            title="finding",
            source_type="ai.log_watch",
            metadata={"payload": {"signal": "ERR", "draft_pr": pr, "triage": {"status": "pending"}}},
        )
        lw = TaskSerializer(task).data["log_watch"]
        assert lw["draft_pr"] == pr

    def test_log_watch_draft_pr_none_when_absent(self, workspace_factory, team_factory):
        from components.project.mappers.rest.project_serializers import TaskSerializer
        from infrastructure.persistence.project.models import Column, Task

        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])
        column = Column.objects.create(
            team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
        )
        task = Task.objects.create(
            team=team,
            workspace=workspace,
            column=column,
            created_by=owner,
            title="finding",
            source_type="ai.log_watch",
            metadata={"payload": {"signal": "ERR", "triage": {"status": "pending"}}},
        )
        assert TaskSerializer(task).data["log_watch"]["draft_pr"] is None
