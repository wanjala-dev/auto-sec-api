"""Query: Fetch agent execution detail and list.

No Django imports — depends only on port.
"""
from __future__ import annotations

from components.agents.application.ports.agent_execution_query_port import (
    AgentExecutionQueryPort,
    AgentMemoryData,
    AgentMemoryRequest,
    ExecutionDetailData,
    ExecutionDetailRequest,
    ExecutionListData,
    ExecutionListRequest,
)


class FetchAgentExecutionDetailQuery:
    """Application query for single execution detail with conversation."""

    def __init__(self, query_port: AgentExecutionQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: ExecutionDetailRequest) -> ExecutionDetailData:
        return self._port.fetch_execution_detail(request=request)


class FetchAgentExecutionListQuery:
    """Application query for paginated execution list."""

    def __init__(self, query_port: AgentExecutionQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: ExecutionListRequest) -> ExecutionListData:
        return self._port.fetch_execution_list(request=request)


class FetchAgentMemoryQuery:
    """Application query for agent memory with conversation history."""

    def __init__(self, query_port: AgentExecutionQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: AgentMemoryRequest) -> AgentMemoryData:
        return self._port.fetch_agent_memory(request=request)
