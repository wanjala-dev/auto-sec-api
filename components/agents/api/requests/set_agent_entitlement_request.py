"""Request DTO for POST /ai/agents/types/entitlements/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SetAgentEntitlementRequest:
    """Input DTO for POST /ai/agents/types/entitlements/ endpoint.

    Enables or disables an agent type for a workspace.
    """
    workspace_id: str
    agent_type: str
    is_enabled: Any
