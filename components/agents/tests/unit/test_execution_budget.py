"""Tests for deep agent execution budget enforcement."""

from __future__ import annotations

import time

from components.agents.domain.value_objects.plan_schemas import ExecutionBudget, PlanState
from components.agents.infrastructure.adapters.langchain.deep.orchestrator import _check_budget


class TestCheckBudget:
    def _state(self, **overrides) -> PlanState:
        base: PlanState = {
            "iteration_count": 0,
            "worker_failure_count": 0,
            "start_time": time.time(),
            "completed_task_ids": [],
            "pending_tasks": [],
            "budget": ExecutionBudget(
                max_iterations=10,
                max_tasks=20,
                time_budget_seconds=60.0,
                max_worker_failures=3,
            ).model_dump(),
        }
        base.update(overrides)
        return base

    def test_no_budget_returns_none(self):
        assert _check_budget({"budget": None}) is None

    def test_within_budget_returns_none(self):
        assert _check_budget(self._state(iteration_count=5)) is None

    def test_max_iterations_exceeded(self):
        reason = _check_budget(self._state(iteration_count=10))
        assert reason is not None
        assert "max_iterations" in reason

    def test_max_tasks_exceeded(self):
        tasks = [{"id": str(i)} for i in range(15)]
        reason = _check_budget(
            self._state(
                completed_task_ids=[str(i) for i in range(10)],
                pending_tasks=tasks,
            )
        )
        assert reason is not None
        assert "max_tasks" in reason

    def test_time_budget_exceeded(self):
        reason = _check_budget(self._state(start_time=time.time() - 120))
        assert reason is not None
        assert "time_budget" in reason

    def test_max_worker_failures_exceeded(self):
        # Legacy last-value channel fallback (external writers / old checkpoints).
        reason = _check_budget(self._state(worker_failure_count=3))
        assert reason is not None
        assert "max_worker_failures" in reason

    def test_max_worker_failures_derived_from_failure_records(self):
        # Canonical path: failures live in run_metadata["worker_failures"]
        # (reducer-united across concurrent workers); the count is derived.
        reason = _check_budget(
            self._state(
                worker_failure_count=0,
                run_metadata={"worker_failures": {"t1": {}, "t2": {}, "t3": {}}},
            )
        )
        assert reason is not None
        assert "max_worker_failures" in reason

    def test_worker_failures_baseline_resets_derived_count(self):
        # replan_bookkeeping stamps the baseline watermark instead of deleting
        # records — failures below it must not count against the cap.
        reason = _check_budget(
            self._state(
                worker_failure_count=0,
                run_metadata={
                    "worker_failures": {"t1": {}, "t2": {}, "t3": {}},
                    "worker_failures_baseline": 2,
                },
            )
        )
        assert reason is None

    def test_budget_not_exceeded_at_boundary(self):
        # Exactly at max_iterations - 1 should be fine
        assert _check_budget(self._state(iteration_count=9)) is None

    def test_default_budget_has_safe_limits(self):
        budget = ExecutionBudget()
        assert budget.max_iterations == 50
        assert budget.max_tasks == 100
        assert budget.time_budget_seconds == 300.0
        assert budget.max_worker_failures == 10
