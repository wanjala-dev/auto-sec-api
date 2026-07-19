"""
LangChain implementation of AgentRuntimePort.

This adapter bridges the framework-agnostic ``AgentRuntimePort`` to the
LangChain-specific ``BaseAgent`` / ``AgentRegistry`` classes that live
alongside it in ``infrastructure/adapters/langchain/``.

To swap to LlamaIndex, create ``infrastructure/adapters/llamaindex/runtime_adapter.py``
implementing the same port — no application or domain code changes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from components.agents.application.ports.agent_runtime_port import (
    AgentHandle,
    AgentResult,
    AgentRuntimePort,
)


class LangChainRuntimeAdapter(AgentRuntimePort):
    """Adapts LangChain's BaseAgent/AgentRegistry to AgentRuntimePort."""

    # ------------------------------------------------------------------
    # Port implementation
    # ------------------------------------------------------------------

    def create_agent(
        self,
        agent_type: str,
        agent_id: str,
        user_id: str,
        workspace_id: str,
        *,
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AgentHandle:
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        merged = {**(config or {}), **kwargs}
        agent_instance = AgentRegistry.create_agent(
            name=agent_type,
            agent_id=agent_id,
            user_id=user_id,
            workspace_id=workspace_id,
            **merged,
        )
        return AgentHandle(
            agent_id=agent_id,
            agent_type=agent_type,
            _impl=agent_instance,
        )

    def execute(
        self,
        handle: AgentHandle,
        query: str,
        *,
        conversation_id: Optional[str] = None,
        callbacks: Optional[List[Any]] = None,
        **kwargs: Any,
    ) -> AgentResult:
        agent = handle._impl
        try:
            result = agent.execute(query, **kwargs)
            return AgentResult(
                output=result.get("output", ""),
                intermediate_steps=result.get("intermediate_steps", []),
                metadata=result.get("metadata", {}),
                status="completed",
            )
        except Exception as exc:
            return AgentResult(
                output="",
                error=str(exc),
                status="failed",
            )

    def list_registered_types(self) -> List[str]:
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        return list(AgentRegistry._registry.keys())

    def is_type_registered(self, agent_type: str) -> bool:
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        return agent_type in AgentRegistry._registry
