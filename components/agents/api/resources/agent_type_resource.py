"""Response DTO for agent type endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentTypeResource:
    """An available agent type."""
    agent_type: str
    id: str | None = None
    name: str | None = None
    description: str | None = None
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentTypesCollectionResource:
    """Output DTO for agent types list endpoints."""
    agent_types: list[AgentTypeResource] = field(default_factory=list)
    total: int = 0


@dataclass(frozen=True)
class EntitlementResource:
    """Agent type entitlement for a workspace."""
    entitlement_id: str
    workspace_id: str
    agent_type: str
    is_enabled: bool
