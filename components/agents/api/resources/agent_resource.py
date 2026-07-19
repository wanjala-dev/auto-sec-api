"""Response DTO for agent-related endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EngagementCountsResource:
    """Engagement statistics for an agent."""
    likes: int = 0
    followers: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    comment_count: int = 0


@dataclass(frozen=True)
class AgentResource:
    """Output DTO for agent detail endpoints."""
    agent_id: str
    id: str | None = None
    name: str | None = None
    agent_type: str | None = None
    workspace_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    is_disabled: bool = False
    status: str | None = None
    description: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)
    engagement_counts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentCollectionResource:
    """Output DTO for agent list endpoints."""
    agents: list[AgentResource] = field(default_factory=list)
    total: int = 0
    count: int = 0
