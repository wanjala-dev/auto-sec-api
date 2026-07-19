"""Cost tracking and token budget enforcement.

Accumulates token usage per workspace/agent and enforces spending limits.
When a workspace exceeds its budget, the tracker signals downgrade or block.

Pure domain service — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from components.agents.domain.enums import ModelTier


class BudgetAction(StrEnum):
    """What to do when a budget threshold is hit."""

    ALLOW = "allow"                # Under budget — proceed normally
    DOWNGRADE_TIER = "downgrade"   # Over soft limit — use cheaper model
    BLOCK = "block"                # Over hard limit — reject request
    WARN = "warn"                  # Approaching limit — proceed but alert


@dataclass(frozen=True)
class TokenBudget:
    """Spending limits for a workspace or agent."""

    workspace_id: str
    daily_token_limit: int = 500_000        # Tokens per day
    monthly_token_limit: int = 10_000_000   # Tokens per month
    daily_cost_limit_usd: float = 5.0       # USD per day
    monthly_cost_limit_usd: float = 100.0   # USD per month
    soft_limit_pct: float = 0.8             # Warn/downgrade at 80%
    hard_limit_pct: float = 1.0             # Block at 100%


@dataclass
class UsageAccumulator:
    """Running totals for token usage within a time window."""

    workspace_id: str
    period_start: datetime = field(default_factory=datetime.utcnow)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    request_count: int = 0
    by_agent_type: dict[str, int] = field(default_factory=dict)
    by_model_tier: dict[str, int] = field(default_factory=dict)

    def record(
        self,
        tokens: int,
        cost_usd: float,
        agent_type: str = "",
        model_tier: str = "",
    ) -> None:
        """Record a single execution's usage."""
        self.total_tokens += tokens
        self.total_cost_usd += cost_usd
        self.request_count += 1
        if agent_type:
            self.by_agent_type[agent_type] = self.by_agent_type.get(agent_type, 0) + tokens
        if model_tier:
            self.by_model_tier[model_tier] = self.by_model_tier.get(model_tier, 0) + tokens


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of checking usage against budget."""

    action: BudgetAction
    reason: str
    usage_pct: float = 0.0
    recommended_tier: str = ""

    @property
    def should_proceed(self) -> bool:
        return self.action in (BudgetAction.ALLOW, BudgetAction.WARN, BudgetAction.DOWNGRADE_TIER)

    @property
    def should_downgrade(self) -> bool:
        return self.action == BudgetAction.DOWNGRADE_TIER


class CostTracker:
    """Evaluate usage against budget and recommend action.

    This is a pure domain service — callers provide the current
    accumulator and budget; the tracker does the maths.
    """

    def check_budget(
        self,
        usage: UsageAccumulator,
        budget: TokenBudget,
    ) -> BudgetCheckResult:
        """Check current usage against the budget and return recommended action."""

        # Check daily token limit
        token_pct = usage.total_tokens / max(budget.daily_token_limit, 1)
        cost_pct = usage.total_cost_usd / max(budget.daily_cost_limit_usd, 0.01)

        # Use the higher of the two percentages
        usage_pct = max(token_pct, cost_pct)

        if usage_pct >= budget.hard_limit_pct:
            return BudgetCheckResult(
                action=BudgetAction.BLOCK,
                reason=f"Daily budget exceeded ({usage_pct:.0%} of limit)",
                usage_pct=usage_pct,
            )

        if usage_pct >= budget.soft_limit_pct:
            return BudgetCheckResult(
                action=BudgetAction.DOWNGRADE_TIER,
                reason=f"Approaching daily limit ({usage_pct:.0%}), downgrading model tier",
                usage_pct=usage_pct,
                recommended_tier=ModelTier.TIER_1,
            )

        if usage_pct >= budget.soft_limit_pct * 0.8:
            return BudgetCheckResult(
                action=BudgetAction.WARN,
                reason=f"Usage at {usage_pct:.0%} of daily limit",
                usage_pct=usage_pct,
            )

        return BudgetCheckResult(
            action=BudgetAction.ALLOW,
            reason="Under budget",
            usage_pct=usage_pct,
        )

    def get_recommended_tier(
        self,
        current_tier: str,
        budget_result: BudgetCheckResult,
    ) -> str:
        """Return the tier to use based on budget status."""
        if budget_result.should_downgrade and budget_result.recommended_tier:
            return budget_result.recommended_tier
        return current_tier
