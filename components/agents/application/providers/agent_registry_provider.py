"""Provider/composition root for the agent registry.

Resources / controllers that need to translate an agent slug into a
canonical name or display label go through this provider instead of
importing the concrete ``AgentRegistry`` directly.
"""

from __future__ import annotations

from typing import Any


class AgentRegistryProvider:
    def canonical_name_for(self, agent_type: str) -> str:
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        return AgentRegistry.canonical_name_for(agent_type)

    def display_name_for(self, agent_type: str) -> str:
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        return AgentRegistry.display_name_for(agent_type)

    def is_agent_registered(self, agent_type: str) -> bool:
        """True if an agent class is registered under *agent_type* (or an alias)."""
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        return AgentRegistry.get_agent_class(agent_type) is not None


    @staticmethod
    def _resolve_agent_id(*, agent_type: str, workspace_id):
        """This workspace's agent of that type, or None.

        Workspace-scoped, always: evaluating another tenant's agent would be a
        cross-tenant read, and on the pooled tier this filter IS the boundary.
        Ordered so repeated runs pick the same agent rather than an arbitrary
        one — an eval whose subject changes between runs is not a comparison.
        """
        from infrastructure.persistence.ai.agents.models import Agent

        row = (
            Agent.objects.filter(agent_type=agent_type, workspace_id=workspace_id)
            .order_by("created_at" if hasattr(Agent, "created_at") else "agent_id")
            .values_list("agent_id", flat=True)
            .first()
        )
        return str(row) if row else None

    def run_in_evaluation_mode(
        self, *, agent_type: str, user_id, workspace_id, model_slug: str, query: str, agent_id: str | None = None
    ) -> dict:
        """Build and run an agent with writes refused (ADR 0033 D5).

        Lives here, in `agents`' own application layer, because reaching the
        concrete `AgentRegistry` from another context's infrastructure is a
        boundary violation — `test_cross_context_infrastructure_boundary`
        rightly refuses it. A provider IS the composition root, so the lazy
        import below is legitimate here and nowhere else.

        `execution_mode` is passed at CONSTRUCTION: `BaseAgent.__init__` copies
        kwargs onto `self.config`, and `_risk_gated` reads it on every tool
        call. A mode set after the executor is built is a mode that was
        briefly absent.
        """
        from components.agents.application.policies.tool_risk import (
            EVALUATION_EXECUTION_MODE,
        )
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        agent_class = AgentRegistry.get_agent_class(agent_type)
        if agent_class is None:
            return {"success": False, "error": f"unknown agent type '{agent_type}'"}

        # An eval measures THIS WORKSPACE'S agent, so it has to run AS that
        # agent — `agent_id` is the primary key of a real `Agent` row, and
        # `memory_service` loads it with `Agent.objects.get(agent_id=...)`.
        #
        # The caller used to mint a fresh UUID. That failed two ways in
        # succession: first as "is not a valid UUID" when the value carried an
        # `eval-` prefix, then as "Agent matching query does not exist" once the
        # format was right but the row was not. The second failure is the real
        # one — a synthetic id would have evaluated a memory-less agent that no
        # customer runs, which is not the thing ADR 0033 set out to measure.
        if agent_id is None:
            agent_id = self._resolve_agent_id(agent_type=agent_type, workspace_id=workspace_id)
            if agent_id is None:
                return {
                    "success": False,
                    "error": (
                        f"this workspace has no '{agent_type}' agent to evaluate — "
                        "an evaluation scores the agent you actually run"
                    ),
                }

        agent = agent_class(
            agent_id=agent_id,
            user_id=user_id,
            workspace_id=workspace_id,
            execution_mode=EVALUATION_EXECUTION_MODE,
            model=model_slug or None,
        )
        result = agent.execute(query)
        return result if isinstance(result, dict) else {"success": True, "response": str(result)}


_default = AgentRegistryProvider()


def get_agent_registry_provider() -> AgentRegistryProvider:
    return _default
