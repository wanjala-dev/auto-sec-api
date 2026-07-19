"""
Port for agent execution runtime.

This abstracts the underlying agent framework (LangChain, LlamaIndex,
CrewAI, etc.) so the application layer never couples to a specific
vendor's agent executor.  Swapping frameworks means writing a new
adapter under ``infrastructure/adapters/<framework>/`` — nothing else
in the application or domain layers changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Value objects returned by the port ────────────────────────────────

@dataclass
class AgentResult:
    """Framework-agnostic result of an agent execution."""

    output: str
    intermediate_steps: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    status: str = "completed"  # completed | failed | paused


@dataclass
class AgentHandle:
    """Opaque handle wrapping a live agent instance.

    The application layer passes this around without inspecting internals.
    Only the adapter that created it knows the concrete type inside
    ``_impl``.
    """

    agent_id: str
    agent_type: str
    _impl: Any = field(repr=False, default=None)


# ── Port contract ─────────────────────────────────────────────────────

class AgentRuntimePort(ABC):
    """
    Contract every agent-execution framework must implement.

    Adapters live at ``infrastructure/adapters/<framework>/runtime.py``.
    """

    @abstractmethod
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
        """Instantiate a framework-specific agent and return an opaque handle."""

    @abstractmethod
    def execute(
        self,
        handle: AgentHandle,
        query: str,
        *,
        conversation_id: Optional[str] = None,
        callbacks: Optional[List[Any]] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Run *query* through the agent and return a framework-agnostic result."""

    @abstractmethod
    def list_registered_types(self) -> List[str]:
        """Return slugs of all agent types the runtime knows about."""

    @abstractmethod
    def is_type_registered(self, agent_type: str) -> bool:
        """Return *True* when *agent_type* has a registered implementation."""
