"""Port: Agent engagement write operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


# ── Request / Result DTOs ────────────────────────────────────────────

@dataclass(frozen=True)
class EngagementCounts:
    """Engagement statistics for an agent."""

    likes: int = 0
    followers: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    comment_count: int = 0


@dataclass(frozen=True)
class FollowRequest:
    agent_id: str
    user: Any = None


@dataclass
class FollowResult:
    following: bool = False
    engagement_counts: EngagementCounts = field(default_factory=EngagementCounts)


@dataclass(frozen=True)
class LikeRequest:
    agent_id: str
    user: Any = None


@dataclass
class LikeResult:
    liked: bool = False
    engagement_counts: EngagementCounts = field(default_factory=EngagementCounts)


@dataclass(frozen=True)
class RateRequest:
    agent_id: str
    user: Any = None
    score: int = 0
    comment: str = ""


@dataclass
class RateResult:
    rated: bool = False
    engagement_counts: EngagementCounts = field(default_factory=EngagementCounts)


@dataclass(frozen=True)
class CommentRequest:
    agent_id: str
    user: Any = None
    body: str = ""
    parent_id: Any = None


@dataclass
class CommentResult:
    commented: bool = False
    engagement_counts: EngagementCounts = field(default_factory=EngagementCounts)


@dataclass(frozen=True)
class ShareRequest:
    agent_id: str
    user: Any = None
    scope: str = ""
    expires_at: Any = None


@dataclass
class ShareResult:
    share_data: dict[str, Any] = field(default_factory=dict)
    share_url: str = ""


@dataclass(frozen=True)
class RevokeShareRequest:
    share_token: str
    user: Any = None


@dataclass
class RevokeShareResult:
    revoked: bool = False


# ── Port ─────────────────────────────────────────────────────────────

class AgentEngagementPort(abc.ABC):
    """Secondary port for agent engagement write operations."""

    @abc.abstractmethod
    def follow_agent(self, *, request: FollowRequest) -> FollowResult:
        """Follow an agent.

        Raises LookupError if agent not found.
        Raises PermissionError if access denied or agent disabled.
        """
        ...

    @abc.abstractmethod
    def unfollow_agent(self, *, request: FollowRequest) -> FollowResult:
        """Unfollow an agent.

        Raises LookupError if agent not found.
        """
        ...

    @abc.abstractmethod
    def like_agent(self, *, request: LikeRequest, http_request: Any = None) -> LikeResult:
        """Like an agent.

        Raises LookupError if agent not found.
        Raises PermissionError if access denied or agent disabled.
        """
        ...

    @abc.abstractmethod
    def unlike_agent(self, *, request: LikeRequest) -> LikeResult:
        """Remove like from an agent.

        Raises LookupError if agent not found.
        """
        ...

    @abc.abstractmethod
    def rate_agent(self, *, request: RateRequest, http_request: Any = None) -> RateResult:
        """Rate an agent.

        Raises LookupError if agent not found.
        Raises PermissionError if access denied, agent disabled, or ratings disabled.
        Raises ValueError if score invalid.
        """
        ...

    @abc.abstractmethod
    def comment_agent(self, *, request: CommentRequest, http_request: Any = None) -> CommentResult:
        """Add a comment to an agent.

        Raises LookupError if agent not found.
        Raises PermissionError if access denied, agent disabled, or comments disabled.
        Raises ValueError if body invalid or parent invalid.
        """
        ...

    @abc.abstractmethod
    def share_agent(self, *, request: ShareRequest, http_request: Any = None) -> ShareResult:
        """Create a share token for an agent.

        Raises LookupError if agent not found.
        Raises PermissionError if no manage permission.
        Raises ValueError if scope or expires_at invalid.
        """
        ...

    @abc.abstractmethod
    def revoke_share(self, *, request: RevokeShareRequest, http_request: Any = None) -> RevokeShareResult:
        """Revoke a share token.

        Raises LookupError if share not found.
        Raises PermissionError if no manage permission.
        """
        ...
