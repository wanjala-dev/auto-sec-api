"""Deterministic aggregation core of the AgentRunQualityDetector (task #46).

Pure unit — no DB, no LLM. Pins the sustained-vs-blip gate, each metric's
numerator/denominator definition, and the evidence contract of a breach.
"""

from __future__ import annotations

from components.agents.infrastructure.adapters.actions.detectors.run_quality import (
    METRIC_BUDGET_TRIPS,
    METRIC_NEEDS_HUMAN,
    METRIC_RETRY,
    METRIC_RUBRIC_FIRST_PASS_FAIL,
    _rubric_first_pass_failed,
    aggregate_run_quality,
)

CFG = {
    "min_findings": 5,
    "needs_human_rate_threshold": 0.5,
    "rubric_first_pass_fail_rate_threshold": 0.5,
    "retry_rate_threshold": 0.5,
    "budget_trip_min": 2,
    "max_sample_task_ids": 10,
}


def _obs(
    i,
    *,
    agent="triage_agent",
    needs_human=False,
    rubric=None,
    retries=None,
    budget_exceeded=None,
    has_telemetry=False,
):
    return {
        "id": f"f-{i}",
        "agent": agent,
        "needs_human": needs_human,
        "rubric": rubric,
        "retries": retries,
        "budget_exceeded": budget_exceeded,
        "has_telemetry": has_telemetry,
    }


class TestSustainedVsBlip:
    def test_sustained_needs_human_breach_files(self):
        # 6 handled findings, 4 flagged needs_human → 66% > 50% over ≥5.
        rows = [_obs(i, needs_human=(i < 4)) for i in range(6)]
        breaches = aggregate_run_quality(rows, CFG)
        assert len(breaches) == 1
        b = breaches[0]
        assert b["metric"] == METRIC_NEEDS_HUMAN
        assert b["agent_type"] == "triage_agent"
        assert b["numerator"] == 4 and b["denominator"] == 6
        assert b["value"] == round(4 / 6, 4)

    def test_blip_below_min_findings_never_files(self):
        # 3 findings ALL needs_human (100%) — still a blip, not a signal.
        rows = [_obs(i, needs_human=True) for i in range(3)]
        assert aggregate_run_quality(rows, CFG) == []

    def test_rate_at_threshold_does_not_file(self):
        # Exactly 50% is not "> threshold".
        rows = [_obs(i, needs_human=(i % 2 == 0)) for i in range(6)]
        assert aggregate_run_quality(rows, CFG) == []

    def test_agents_are_aggregated_independently(self):
        bad = [_obs(f"a{i}", agent="triage_agent", needs_human=True) for i in range(5)]
        good = [_obs(f"b{i}", agent="optimization_agent", needs_human=False) for i in range(5)]
        breaches = aggregate_run_quality(bad + good, CFG)
        assert [b["agent_type"] for b in breaches] == ["triage_agent"]


class TestRubricFirstPass:
    def test_first_pass_failure_classification(self):
        assert _rubric_first_pass_failed({"verdict": "satisfied", "iterations": 1}) is False
        assert _rubric_first_pass_failed({"verdict": "satisfied", "iterations": 2}) is True  # revision demanded
        assert _rubric_first_pass_failed({"verdict": "failed", "iterations": 1}) is True
        assert _rubric_first_pass_failed({"verdict": "max_iterations_reached", "iterations": 2}) is True
        assert _rubric_first_pass_failed(None) is None  # ungraded → excluded, not "clean"

    def test_denominator_is_graded_findings_only(self):
        graded_bad = [_obs(i, rubric={"verdict": "failed", "iterations": 1}, has_telemetry=True) for i in range(4)]
        graded_ok = [
            _obs(10 + i, rubric={"verdict": "satisfied", "iterations": 1}, has_telemetry=True) for i in range(2)
        ]
        ungraded = [_obs(20 + i, has_telemetry=True) for i in range(10)]  # must not dilute the rate
        breaches = aggregate_run_quality(graded_bad + graded_ok + ungraded, CFG)
        rubric = [b for b in breaches if b["metric"] == METRIC_RUBRIC_FIRST_PASS_FAIL]
        assert len(rubric) == 1
        assert rubric[0]["denominator"] == 6 and rubric[0]["numerator"] == 4

    def test_graded_below_min_findings_is_a_blip(self):
        rows = [_obs(i, rubric={"verdict": "failed", "iterations": 1}, has_telemetry=True) for i in range(4)]
        breaches = aggregate_run_quality(rows, CFG)
        assert [b for b in breaches if b["metric"] == METRIC_RUBRIC_FIRST_PASS_FAIL] == []


class TestRetryAndBudgetMetrics:
    def test_retry_rate_over_telemetry_bearing_only(self):
        retried = [_obs(i, retries=1, has_telemetry=True) for i in range(4)]
        clean = [_obs(10 + i, retries=0, has_telemetry=True) for i in range(2)]
        legacy = [_obs(20 + i) for i in range(10)]  # pre-telemetry rows excluded
        breaches = aggregate_run_quality(retried + clean + legacy, CFG)
        retry = [b for b in breaches if b["metric"] == METRIC_RETRY]
        assert len(retry) == 1
        assert retry[0]["denominator"] == 6 and retry[0]["numerator"] == 4

    def test_budget_trips_use_absolute_count(self):
        tripped = [_obs(i, budget_exceeded="max_cost_usd ($0.50) reached", has_telemetry=True) for i in range(2)]
        clean = [_obs(10 + i, has_telemetry=True) for i in range(8)]
        breaches = aggregate_run_quality(tripped + clean, CFG)
        budget = [b for b in breaches if b["metric"] == METRIC_BUDGET_TRIPS]
        assert len(budget) == 1
        assert budget[0]["numerator"] == 2

    def test_single_budget_trip_is_a_blip(self):
        rows = [_obs(0, budget_exceeded="reason", has_telemetry=True)] + [
            _obs(10 + i, has_telemetry=True) for i in range(8)
        ]
        breaches = aggregate_run_quality(rows, CFG)
        assert [b for b in breaches if b["metric"] == METRIC_BUDGET_TRIPS] == []


class TestEvidenceContract:
    def test_breach_carries_auditable_numbers_and_samples(self):
        rows = [_obs(i, needs_human=True) for i in range(12)]
        (breach,) = aggregate_run_quality(rows, CFG)
        assert set(breach) == {
            "agent_type",
            "metric",
            "value",
            "threshold",
            "numerator",
            "denominator",
            "sample_task_ids",
        }
        assert breach["sample_task_ids"] == [f"f-{i}" for i in range(10)]  # capped at max_sample_task_ids
