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


_default = AgentRegistryProvider()


def get_agent_registry_provider() -> AgentRegistryProvider:
    return _default
