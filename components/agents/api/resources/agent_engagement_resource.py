"""Response DTO for agent engagement endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RatingResource:
    """A single rating for an agent."""
    id: str
    agent_id: str
    user_id: str
    score: int
    comment: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class RatingCollectionResource:
    """Output DTO for agent ratings list endpoints."""
    ratings: list[RatingResource] = field(default_factory=list)
    count: int = 0
    next_url: str | None = None
    previous_url: str | None = None


@dataclass(frozen=True)
class CommentResource:
    """A single comment on an agent."""
    id: str
    agent_id: str
    user_id: str
    body: str
    parent_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    replies: list[CommentResource] = field(default_factory=list)


@dataclass(frozen=True)
class CommentCollectionResource:
    """Output DTO for agent comments list endpoints."""
    comments: list[CommentResource] = field(default_factory=list)
    count: int = 0
    next_url: str | None = None
    previous_url: str | None = None


@dataclass(frozen=True)
class ShareTokenResource:
    """A share token for an agent."""
    share_token: str
    agent_id: str
    scope: str
    created_at: str | None = None
    expires_at: str | None = None
    created_by: str | None = None
    share_url: str | None = None


@dataclass(frozen=True)
class EngagementResource:
    """Output DTO for engagement action endpoints (follow, like, rate, comment)."""
    agent_id: str
    action: str
    success: bool
    following: bool | None = None
    liked: bool | None = None
    rated: bool | None = None
    commented: bool | None = None
    engagement_counts: dict[str, Any] = field(default_factory=dict)
