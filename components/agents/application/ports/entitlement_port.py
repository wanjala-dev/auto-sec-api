"""Port for agent-type entitlement checks."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EntitlementPort(ABC):

    @abstractmethod
    def is_agent_enabled_for_workspace(self, workspace_id: str, agent_type: str) -> bool: ...
