"""Query: Fetch agent graph dashboard data.

No Django imports — depends only on port.
"""
from __future__ import annotations

from typing import Any

from components.agents.application.ports.agent_graph_query_port import (
    AgentGraphData,
    AgentGraphQueryPort,
    AgentGraphRequest,
)


class FetchAgentGraphQuery:
    """Application query for the agent graph dashboard."""

    def __init__(self, query_port: AgentGraphQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: AgentGraphRequest, http_request: Any) -> AgentGraphData:
        return self._port.fetch_graph(request=request, http_request=http_request)
