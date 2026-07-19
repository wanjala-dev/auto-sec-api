"""Query: Agent engagement read operations.

No Django imports — depends only on port.
"""
from __future__ import annotations

from components.agents.application.ports.agent_engagement_query_port import (
    AgentEngagementQueryPort,
    GetSharedAgentRequest,
    ListCommentsData,
    ListCommentsRequest,
    ListRatingsData,
    ListRatingsRequest,
    SharedAgentData,
)


class FetchAgentRatingsQuery:
    """Application query for paginated agent ratings."""

    def __init__(self, query_port: AgentEngagementQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: ListRatingsRequest, http_request=None) -> ListRatingsData:
        return self._port.list_ratings(request=request, http_request=http_request)


class FetchAgentCommentsQuery:
    """Application query for paginated agent comments with replies."""

    def __init__(self, query_port: AgentEngagementQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: ListCommentsRequest, http_request=None) -> ListCommentsData:
        return self._port.list_comments(request=request, http_request=http_request)


class FetchSharedAgentQuery:
    """Application query for shared agent details via token."""

    def __init__(self, query_port: AgentEngagementQueryPort) -> None:
        self._port = query_port

    def execute(self, *, request: GetSharedAgentRequest) -> SharedAgentData:
        return self._port.get_shared_agent(request=request)
