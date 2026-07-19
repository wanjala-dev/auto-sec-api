"""Response DTO for agent profile endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentProfileResource:
    """Output DTO for agent profile detail endpoints."""
    agent_id: str
    profile: dict[str, Any] = field(default_factory=dict)
    engagement_counts: dict[str, Any] = field(default_factory=dict)
    is_disabled: bool = False
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentStateResource:
    """Output DTO for agent state endpoints."""
    agent_id: str
    state: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] | None = None
    engagement_counts: dict[str, Any] = field(default_factory=dict)
    is_disabled: bool = False
    status: str | None = None
