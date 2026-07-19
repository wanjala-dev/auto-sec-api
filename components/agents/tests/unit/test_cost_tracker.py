"""Unit tests for CostTracker and budget enforcement."""

import pytest

from components.agents.domain.services.cost_tracker import (
    BudgetAction,
    BudgetCheckResult,
    CostTracker,
    TokenBudget,
    UsageAccumulator,
)


class TestCostTracker:
    def setup_method(self):
        self.tracker = CostTracker()
        self.budget = TokenBudget(workspace_id="ws-1")

    def test_under_budget_allowed(self):
        usage = UsageAccumulator(workspace_id="ws-1", total_tokens=100_000)
        result = self.tracker.check_budget(usage, self.budget)
        assert result.action == BudgetAction.ALLOW
        assert result.should_proceed

    def test_over_hard_limit_blocked(self):
        usage = UsageAccumulator(
            workspace_id="ws-1",
            total_tokens=600_000,  # > 500k daily limit
        )
        result = self.tracker.check_budget(usage, self.budget)
        assert result.action == BudgetAction.BLOCK
        assert not result.should_proceed

    def test_at_soft_limit_downgrade(self):
        usage = UsageAccumulator(
            workspace_id="ws-1",
            total_tokens=410_000,  # 82% of 500k → above 80% soft limit
        )
        result = self.tracker.check_budget(usage, self.budget)
        assert result.action == BudgetAction.DOWNGRADE_TIER
        assert result.should_proceed
        assert result.should_downgrade

    def test_approaching_limit_warns(self):
        usage = UsageAccumulator(
            workspace_id="ws-1",
            total_tokens=330_000,  # 66% → above 64% (80% of 80%)
        )
        result = self.tracker.check_budget(usage, self.budget)
        assert result.action == BudgetAction.WARN
        assert result.should_proceed

    def test_cost_based_limit(self):
        usage = UsageAccumulator(
            workspace_id="ws-1",
            total_tokens=1000,
            total_cost_usd=11.0,  # > $10 daily cap
        )
        result = self.tracker.check_budget(usage, self.budget)
        assert result.action == BudgetAction.BLOCK

    def test_usage_accumulator_record(self):
        usage = UsageAccumulator(workspace_id="ws-1")
        usage.record(tokens=1000, cost_usd=0.01, agent_type="budget_agent", model_tier="tier_1")
        usage.record(tokens=2000, cost_usd=0.05, agent_type="budget_agent", model_tier="tier_2")
        assert usage.total_tokens == 3000
        # 0.01 + 0.05 in binary floats lands at 0.060000000000000005 — use
        # pytest.approx so the test stays meaningful without an FX-style
        # rounding wrapper in production cost accounting (the cost is
        # still summed with float arithmetic).
        assert usage.total_cost_usd == pytest.approx(0.06)
        assert usage.request_count == 2
        assert usage.by_agent_type["budget_agent"] == 3000
        assert usage.by_model_tier["tier_1"] == 1000
        assert usage.by_model_tier["tier_2"] == 2000
