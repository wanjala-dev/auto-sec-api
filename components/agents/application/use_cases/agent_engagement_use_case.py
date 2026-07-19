"""Use cases: Agent engagement write operations.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from components.agents.application.ports.agent_engagement_port import (
    AgentEngagementPort,
    CommentRequest,
    CommentResult,
    FollowRequest,
    FollowResult,
    LikeRequest,
    LikeResult,
    RateRequest,
    RateResult,
    RevokeShareRequest,
    RevokeShareResult,
    ShareRequest,
    ShareResult,
)


class FollowAgentUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: FollowRequest) -> FollowResult:
        return self._port.follow_agent(request=request)


class UnfollowAgentUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: FollowRequest) -> FollowResult:
        return self._port.unfollow_agent(request=request)


class LikeAgentUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: LikeRequest, http_request=None) -> LikeResult:
        return self._port.like_agent(request=request, http_request=http_request)


class UnlikeAgentUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: LikeRequest) -> LikeResult:
        return self._port.unlike_agent(request=request)


class RateAgentUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: RateRequest, http_request=None) -> RateResult:
        return self._port.rate_agent(request=request, http_request=http_request)


class CommentAgentUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: CommentRequest, http_request=None) -> CommentResult:
        return self._port.comment_agent(request=request, http_request=http_request)


class ShareAgentUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: ShareRequest, http_request=None) -> ShareResult:
        return self._port.share_agent(request=request, http_request=http_request)


class RevokeShareUseCase:
    def __init__(self, port: AgentEngagementPort) -> None:
        self._port = port

    def execute(self, *, request: RevokeShareRequest, http_request=None) -> RevokeShareResult:
        return self._port.revoke_share(request=request, http_request=http_request)
