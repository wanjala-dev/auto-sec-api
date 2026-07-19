"""Port: Agent engagement read queries.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ListRatingsRequest:
    agent_id: str
    user: Any = None
    page: int = 1
    page_size: int = 20


@dataclass
class ListRatingsData:
    ratings: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    next_url: str | None = None
    previous_url: str | None = None


@dataclass(frozen=True)
class ListCommentsRequest:
    agent_id: str
    user: Any = None
    page: int = 1
    page_size: int = 20


@dataclass
class ListCommentsData:
    comments: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    next_url: str | None = None
    previous_url: str | None = None


@dataclass(frozen=True)
class GetSharedAgentRequest:
    share_token: str
    user: Any = None


@dataclass
class SharedAgentData:
    agent_id: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    engagement_counts: dict[str, Any] = field(default_factory=dict)
    is_disabled: bool = False


class AgentEngagementQueryPort(abc.ABC):
    """Secondary port for agent engagement read queries."""

    @abc.abstractmethod
    def list_ratings(self, *, request: ListRatingsRequest, http_request: Any = None) -> ListRatingsData:
        """Fetch paginated ratings for an agent.

        Raises LookupError if agent not found.
        Raises PermissionError if access denied.
        """
        ...

    @abc.abstractmethod
    def list_comments(self, *, request: ListCommentsRequest, http_request: Any = None) -> ListCommentsData:
        """Fetch paginated comments with replies for an agent.

        Raises LookupError if agent not found.
        Raises PermissionError if access denied.
        """
        ...

    @abc.abstractmethod
    def get_shared_agent(self, *, request: GetSharedAgentRequest) -> SharedAgentData:
        """Fetch shared agent details via share token.

        Raises LookupError if share not found or expired.
        Raises PermissionError if workspace-only scope and user not authorized.
        """
        ...
