"""Tests for execution cost tracker."""

from __future__ import annotations

from components.agents.application.services.execution_cost_tracker import ExecutionCostTracker


class TestExecutionCostTracker:
    def test_empty_snapshot(self):
        tracker = ExecutionCostTracker()
        snap = tracker.snapshot()
        assert snap["total_tokens"] == 0
        assert snap["total_cost_usd"] == 0.0
        assert snap["total_llm_calls"] == 0
        assert snap["by_model"] == {}

    def test_single_call(self):
        tracker = ExecutionCostTracker()
        tracker.record_llm_call(
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.025,
        )
        snap = tracker.snapshot()
        assert snap["total_input_tokens"] == 1000
        assert snap["total_output_tokens"] == 500
        assert snap["total_tokens"] == 1500
        assert snap["total_cost_usd"] == 0.025
        assert snap["total_llm_calls"] == 1
        assert "gpt-4o" in snap["by_model"]

    def test_multiple_calls_same_model(self):
        tracker = ExecutionCostTracker()
        tracker.record_llm_call(model="claude-3", input_tokens=500, output_tokens=200, cost_usd=0.01)
        tracker.record_llm_call(model="claude-3", input_tokens=300, output_tokens=100, cost_usd=0.005)

        snap = tracker.snapshot()
        assert snap["total_tokens"] == 1100
        assert snap["total_llm_calls"] == 2
        assert snap["by_model"]["claude-3"]["call_count"] == 2
        assert snap["by_model"]["claude-3"]["input_tokens"] == 800

    def test_multiple_models(self):
        tracker = ExecutionCostTracker()
        tracker.record_llm_call(model="gpt-4o", input_tokens=1000, output_tokens=500, cost_usd=0.025)
        tracker.record_llm_call(model="claude-3", input_tokens=500, output_tokens=200, cost_usd=0.01)

        snap = tracker.snapshot()
        assert len(snap["by_model"]) == 2
        assert snap["total_llm_calls"] == 2
        assert snap["total_cost_usd"] == 0.035

    def test_properties(self):
        tracker = ExecutionCostTracker()
        tracker.record_llm_call(input_tokens=100, output_tokens=50, cost_usd=0.005)
        assert tracker.total_tokens == 150
        assert tracker.total_cost_usd == 0.005

    def test_cache_tokens(self):
        tracker = ExecutionCostTracker()
        tracker.record_llm_call(
            model="claude-3",
            input_tokens=500,
            output_tokens=100,
            cache_read_tokens=300,
            cache_write_tokens=200,
            cost_usd=0.008,
        )
        snap = tracker.snapshot()
        model = snap["by_model"]["claude-3"]
        assert model["cache_read_tokens"] == 300
        assert model["cache_write_tokens"] == 200
