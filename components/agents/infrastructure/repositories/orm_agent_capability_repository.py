"""ORM adapter implementing :class:`AgentCapabilityPort`.

Reads and writes the workspace ``triage_agent`` row's capability config — the
exact ``Agent`` ORM access ``SetWorkspaceAgentCapabilityUseCase`` did inline,
moved behind the port so the use case no longer imports persistence.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.config.agent_capabilities import TRIAGE_AGENT_TYPE
from components.agents.application.ports.agent_capability_port import (
    AgentCapabilityPort,
    AgentCapabilityRow,
)


class OrmAgentCapabilityRepository(AgentCapabilityPort):
    def get_or_create_triage_agent(self, *, workspace: Any, actor: Any) -> AgentCapabilityRow:
        from infrastructure.persistence.ai.agents.models import Agent

        agent = Agent.objects.filter(workspace=workspace, agent_type=TRIAGE_AGENT_TYPE).order_by("-created_at").first()
        if agent is not None:
            if not isinstance(agent.config, dict):
                agent.config = {}
            return AgentCapabilityRow(
                agent_id=str(agent.agent_id),
                capabilities=dict(agent.config.get("capabilities") or {}),
                created=False,
                instance=agent,
            )

        # No triage agent yet — provision one so the capability has a row to
        # live on. ``Agent.user`` is non-null; the workspace owner is the
        # natural owner of a workspace-level grant, falling back to the acting
        # owner (the endpoint is owner-gated, so ``actor`` IS the owner).
        owner = getattr(workspace, "workspace_owner", None) or actor
        agent = Agent.objects.create(
            workspace=workspace,
            user=owner,
            agent_type=TRIAGE_AGENT_TYPE,
            config={},
        )
        return AgentCapabilityRow(
            agent_id=str(agent.agent_id),
            capabilities={},
            created=True,
            instance=agent,
        )

    def set_capabilities(self, *, agent: Any, capabilities: dict[str, bool]) -> None:
        merged_config = dict(agent.config or {})
        merged_config["capabilities"] = capabilities
        agent.config = merged_config
        agent.save(update_fields=["config", "updated_at"])

    def get_triage_capabilities(self, *, workspace_id: str) -> dict[str, bool]:
        from infrastructure.persistence.ai.agents.models import Agent

        agent = (
            Agent.objects.filter(workspace_id=str(workspace_id), agent_type=TRIAGE_AGENT_TYPE)
            .order_by("-created_at")
            .only("agent_id", "config")
            .first()
        )
        if agent is not None and isinstance(agent.config, dict):
            raw = agent.config.get("capabilities")
            if isinstance(raw, dict):
                return dict(raw)
        return {}
