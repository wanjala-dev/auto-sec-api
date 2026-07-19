"""Port for token usage tracking and budget persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.agents.domain.services.cost_tracker import (
    TokenBudget,
    UsageAccumulator,
)


class UsageTrackingPort(ABC):
    """Abstract contract for persisting and loading usage data."""

    @abstractmethod
    def get_daily_usage(self, workspace_id: str) -> UsageAccumulator:
        """Load today's accumulated usage for a workspace."""
        ...

    @abstractmethod
    def record_usage(
        self,
        workspace_id: str,
        tokens: int,
        cost_usd: float,
        agent_type: str = "",
        model_tier: str = "",
    ) -> None:
        """Record a single execution's token usage."""
        ...

    @abstractmethod
    def get_budget(self, workspace_id: str) -> TokenBudget:
        """Load the budget configuration for a workspace."""
        ...

    @abstractmethod
    def set_budget(self, budget: TokenBudget) -> None:
        """Persist a budget configuration."""
        ...
