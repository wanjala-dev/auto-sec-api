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


    def run_in_evaluation_mode(
        self, *, agent_type: str, agent_id: str, user_id, workspace_id, model_slug: str, query: str
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
