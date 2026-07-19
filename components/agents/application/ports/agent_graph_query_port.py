"""Port: Agent graph dashboard query.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentGraphRequest:
    """Parsed parameters for agent graph query."""

    workspace_id: str
    agent_type_filter: str | None = None
    include_inactive: bool = False


@dataclass
class AgentGraphData:
    """Aggregated graph data for the agent dashboard.

    Phase 5 of the Agents-as-Teammates migration dropped the
    ``actions`` + ``action_counts`` fields — AI findings now live on
    the workspace's agent team Kanban board and are fetched via
    ``/ai/findings/`` (``AIFindingsViewSet``). This endpoint stays
    focused on agent-level metadata: which agent types are enabled,
    what's currently running, lifetime activity per type.
    """

    agent_types: list[dict[str, Any]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    active_agent_types: list[str] = field(default_factory=list)
    agent_type_activity: list[dict[str, Any]] = field(default_factory=list)
    agent_instances: list[dict[str, Any]] = field(default_factory=list)


class AgentGraphQueryPort(abc.ABC):
    """Secondary port for the agent graph dashboard read query."""

    @abc.abstractmethod
    def fetch_graph(self, *, request: AgentGraphRequest, http_request: Any) -> AgentGraphData:
        """Fetch aggregated graph data for agents in a workspace.

        ``http_request`` is the DRF request, kept on the signature so
        future filters that depend on auth context can use it.
        """
        ...
