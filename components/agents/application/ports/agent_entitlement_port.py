"""Port: Agent entitlement management.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SetEntitlementCommand:
    workspace_id: str
    agent_type_slug: str
    is_enabled: Any  # bool or string-like
    user: Any = None


@dataclass
class EntitlementResult:
    workspace_id: str = ""
    agent_type: str = ""
    is_enabled: bool = False
    entitlement_id: str = ""


@dataclass(frozen=True)
class ListAgentsRequest:
    user_id: str


@dataclass(frozen=True)
class ListAgentTypesRequest:
    workspace_id: str | None = None
    user: Any = None
    include_inactive: bool = False
    enabled_only: bool = False


@dataclass
class ListAgentTypesResult:
    agent_types: list[dict[str, Any]]
    total: int = 0


@dataclass
class ListAgentsResult:
    agents: list[dict[str, Any]]
    total: int = 0


class AgentEntitlementPort(abc.ABC):
    """Secondary port for agent entitlement and listing operations."""

    @abc.abstractmethod
    def set_entitlement(self, *, command: SetEntitlementCommand) -> EntitlementResult:
        """Enable/disable an agent type for a workspace.

        Raises LookupError if workspace or agent type not found.
        Raises PermissionError if user is not workspace owner.
        Raises ValueError for validation failures.
        """
        ...

    @abc.abstractmethod
    def list_agents(self, *, request: ListAgentsRequest) -> ListAgentsResult:
        """List all agents for a user."""
        ...

    @abc.abstractmethod
    def list_agent_types(self, *, request: ListAgentTypesRequest) -> ListAgentTypesResult:
        """List available agent types, optionally filtered by workspace.

        Raises LookupError if workspace not found.
        Raises PermissionError if user lacks access.
        """
        ...
