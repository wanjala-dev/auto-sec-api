"""Pure unit tests for the posture query service (Phase 1 posture slice).

No DB, no LLM — these pin the deterministic aggregation core: median math,
the industry KPI bands, the needs-human/toil split, no-data honesty (explicit
zeros/nulls, never invented numbers), the outlook deltas, and the persona
composition contract (engineer drill-down with ids vs executive NACD shape
over the SAME facts).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from components.agents.application.services.posture_service import (
    BENCHMARK_SOURCE,
    PERSONA_ENGINEER,
    PERSONA_EXECUTIVE,
    RESPONSE_BANDS_HOURS,
    _median,
    compose_posture_report,
    compute_findings_posture,
    compute_fleet_health,
    compute_forward_outlook,
    compute_response_kpis,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _finding(
    i,
    *,
    severity="high",
    kind="ai.log_watch",
    status="todo",
    created_hours_ago=10.0,
    triaged_hours_ago=None,
    needs_human=False,
    agent="triage_agent",
    rubric_verdict=None,
    first_action_hours_ago=None,
):
    triaged_at = (NOW - timedelta(hours=triaged_hours_ago)).isoformat() if triaged_hours_ago is not None else None
    first_action_at = (
        (NOW - timedelta(hours=first_action_hours_ago)).isoformat() if first_action_hours_ago is not None else None
    )
    return {
        "id": f"task-{i}",
        "severity": severity,
        "kind": kind,
        "status": status,
        "created_at": NOW - timedelta(hours=created_hours_ago),
        "triage_status": "triaged" if triaged_at else None,
        "triaged_at": triaged_at,
        "needs_human": needs_human,
        "agent": agent,
        "rubric_verdict": rubric_verdict,
        "first_action_at": first_action_at,
    }


class TestMedian:
    def test_odd_count(self):
        assert _median([5.0, 1.0, 3.0]) == 3.0

    def test_even_count_averages_middle_pair(self):
        assert _median([4.0, 1.0, 2.0, 3.0]) == 2.5

    def test_empty_is_none_not_zero(self):
        # No data → None. Fabricating 0.0 would claim instant response times.
        assert _median([]) is None

    def test_outlier_resistance(self):
        # One pathological 100h straggler must not drag the headline number
        # the way a mean would (vision §2: medians, not means).
        assert _median([1.0, 1.0, 1.0, 1.0, 100.0]) == 1.0


class TestFindingsPosture:
    def test_open_buckets_by_severity_and_kind(self):
        rows = [
            _finding(1, severity="high", kind="ai.log_watch"),
            _finding(2, severity="high", kind="ai.log_optimization"),
            _finding(3, severity="low", kind="ai.log_watch"),
            _finding(4, status="done"),  # closed — not open
            _finding(5, triaged_hours_ago=1.0),  # handled — not open
        ]
        result = compute_findings_posture(rows, now=NOW, window_days=7)

        assert result["open_findings"]["total"] == 3
        assert result["open_findings"]["by_severity"] == {"high": 2, "low": 1}
        assert result["open_findings"]["by_kind"] == {"ai.log_watch": 2, "ai.log_optimization": 1}
        assert set(result["open_findings"]["sample_task_ids"]) == {"task-1", "task-2", "task-3"}
        assert result["no_data"] is False

    def test_oldest_untriaged_age(self):
        rows = [
            _finding(1, created_hours_ago=3.0),
            _finding(2, created_hours_ago=48.0),
            # Older but already triaged — must not win the "untriaged" age.
            _finding(3, created_hours_ago=200.0, triaged_hours_ago=100.0),
        ]
        result = compute_findings_posture(rows, now=NOW, window_days=7)

        assert result["oldest_untriaged_age_hours"] == 48.0
        assert result["oldest_untriaged_task_id"] == "task-2"

    def test_needs_human_backlog_is_open_escalated_cards(self):
        rows = [
            _finding(1, triaged_hours_ago=2.0, needs_human=True),
            _finding(2, triaged_hours_ago=2.0, needs_human=True, status="done"),  # resolved
            _finding(3, triaged_hours_ago=2.0, needs_human=False),
            _finding(4, needs_human=False),  # untriaged — not backlog
        ]
        result = compute_findings_posture(rows, now=NOW, window_days=7)

        assert result["needs_human_backlog"]["count"] == 1
        assert result["needs_human_backlog"]["sample_task_ids"] == ["task-1"]

    def test_toil_split_and_triaged_windows(self):
        rows = [
            _finding(1, triaged_hours_ago=2.0, needs_human=False),  # 24h + window
            _finding(2, triaged_hours_ago=30.0, needs_human=False),  # window only
            _finding(3, triaged_hours_ago=30.0, needs_human=True),  # escalated
            _finding(4, created_hours_ago=400.0, triaged_hours_ago=300.0),  # outside window
        ]
        result = compute_findings_posture(rows, now=NOW, window_days=7)

        assert result["triaged"] == {"last_24h": 1, "last_window": 3}
        assert result["toil"]["handled_total"] == 3
        assert result["toil"]["auto_triaged"] == 2
        assert result["toil"]["escalated_to_human"] == 1
        assert result["toil"]["auto_absorption_rate"] == round(2 / 3, 4)

    def test_empty_data_is_explicit_zeros_and_no_data_flag(self):
        result = compute_findings_posture([], now=NOW, window_days=7)

        assert result["no_data"] is True
        assert result["open_findings"]["total"] == 0
        assert result["open_findings"]["by_severity"] == {}
        assert result["needs_human_backlog"]["count"] == 0
        assert result["oldest_untriaged_age_hours"] is None
        assert result["toil"]["auto_absorption_rate"] is None  # never 0/0 → fabricated 0%


class TestResponseKpis:
    def test_median_latency_per_severity_against_bands(self):
        rows = [
            _finding(1, severity="high", created_hours_ago=10.0, triaged_hours_ago=9.0),  # 1h
            _finding(2, severity="high", created_hours_ago=10.0, triaged_hours_ago=7.0),  # 3h
            _finding(3, severity="high", created_hours_ago=10.0, triaged_hours_ago=9.5),  # 0.5h
            _finding(4, severity="low", created_hours_ago=20.0, triaged_hours_ago=8.0),  # 12h — over band
        ]
        result = compute_response_kpis(rows, window_days=7)

        high = result["triage_latency_by_severity"]["high"]
        assert high["median_hours"] == 1.0
        assert high["band_hours"] == RESPONSE_BANDS_HOURS["high"] == 2.0
        assert high["within_band"] is True
        assert high["sample_count"] == 3

        low = result["triage_latency_by_severity"]["low"]
        assert low["median_hours"] == 12.0
        assert low["band_hours"] == 8.0
        assert low["within_band"] is False

        assert result["benchmark_source"] == BENCHMARK_SOURCE

    def test_unknown_severity_excluded_from_bands_never_guessed(self):
        rows = [_finding(1, severity="", created_hours_ago=10.0, triaged_hours_ago=9.0)]
        result = compute_response_kpis(rows, window_days=7)

        for sev in ("critical", "high", "medium", "low"):
            entry = result["triage_latency_by_severity"][sev]
            assert entry["median_hours"] is None
            assert entry["within_band"] is None
            assert entry["no_data"] is True

    def test_acknowledgment_latency_from_first_action(self):
        rows = [
            _finding(1, created_hours_ago=10.0, triaged_hours_ago=4.0, first_action_hours_ago=8.0),  # ack 2h
            _finding(2, created_hours_ago=10.0, triaged_hours_ago=4.0, first_action_hours_ago=6.0),  # ack 4h
        ]
        result = compute_response_kpis(rows, window_days=7)

        assert result["acknowledgment_latency"]["median_hours"] == 3.0
        assert result["acknowledgment_latency"]["sample_count"] == 2

    def test_no_rows_is_no_data(self):
        result = compute_response_kpis([], window_days=7)
        assert result["no_data"] is True
        assert result["acknowledgment_latency"]["median_hours"] is None
        assert result["acknowledgment_latency"]["no_data"] is True


class TestFleetHealth:
    def test_run_success_rate_over_terminal_runs_only(self):
        runs = [
            {"id": "r1", "status": "completed", "cost_records": []},
            {"id": "r2", "status": "completed", "cost_records": []},
            {"id": "r3", "status": "failed", "cost_records": []},
            {"id": "r4", "status": "running", "cost_records": []},  # not terminal
        ]
        result = compute_fleet_health(runs, [], [], window_days=7)

        deep = result["deep_runs"]
        assert deep["total"] == 4
        assert deep["completed"] == 2 and deep["failed"] == 1 and deep["in_flight"] == 1
        assert deep["success_rate"] == round(2 / 3, 4)

    def test_cost_sums_priced_records_and_counts_unpriced_honestly(self):
        runs = [
            {"id": "r1", "status": "completed", "cost_records": [{"cost_usd": 0.02}, {"cost_usd": None}]},
            {"id": "r2", "status": "completed", "cost_records": [{"cost_usd": 0.03}]},
        ]
        result = compute_fleet_health(runs, [], [], window_days=7)

        assert result["cost"]["total_cost_usd"] == 0.05
        assert result["cost"]["priced_records"] == 2
        assert result["cost"]["unpriced_records"] == 1  # unpriced tokens are NOT priced as $0 silently
        assert result["cost"]["cost_per_day_usd"] == round(0.05 / 7, 6)

    def test_rubric_distribution_and_pass_rate_over_graded_only(self):
        handled = [
            {"id": "t1", "agent": "triage_agent", "rubric_verdict": "satisfied"},
            {"id": "t2", "agent": "triage_agent", "rubric_verdict": "failed"},
            {"id": "t3", "agent": "optimization_agent", "rubric_verdict": None},  # ungraded
        ]
        result = compute_fleet_health([], handled, [], window_days=7)

        rubric = result["rubric_verdicts"]
        assert rubric["graded_total"] == 2
        assert rubric["by_verdict"] == {"satisfied": 1, "failed": 1}
        assert rubric["pass_rate"] == 0.5  # ungraded excluded — never counted as a pass
        assert result["dispatches"]["by_agent"] == {"triage_agent": 2, "optimization_agent": 1}

    def test_human_votes_ratio(self):
        feedback = [{"rating": "up"}, {"rating": "up"}, {"rating": "down"}]
        result = compute_fleet_health([], [], feedback, window_days=7)

        votes = result["human_feedback"]
        assert votes["up"] == 2 and votes["down"] == 1
        assert votes["up_ratio"] == round(2 / 3, 4)

    def test_empty_everything_flags_no_data_per_section(self):
        result = compute_fleet_health([], [], [], window_days=7)

        assert result["deep_runs"]["no_data"] is True
        assert result["deep_runs"]["success_rate"] is None
        assert result["rubric_verdicts"]["no_data"] is True
        assert result["cost"]["no_data"] is True
        assert result["human_feedback"]["no_data"] is True
        assert result["human_feedback"]["up_ratio"] is None


class TestForwardOutlook:
    def test_rising_delta_and_pct(self):
        result = compute_forward_outlook(
            findings_this_week=12,
            findings_last_week=8,
            escalations_this_week=3,
            escalations_last_week=1,
            needs_human_backlog=5,
        )

        created = result["findings_created"]
        assert created["delta"] == 4
        assert created["pct_change"] == 0.5
        assert created["direction"] == "rising"
        assert result["needs_human_escalations"]["delta"] == 2
        assert result["needs_human_backlog_now"] == 5
        assert result["no_data"] is False

    def test_falling_and_flat_directions(self):
        falling = compute_forward_outlook(
            findings_this_week=2,
            findings_last_week=6,
            escalations_this_week=0,
            escalations_last_week=0,
            needs_human_backlog=0,
        )
        assert falling["findings_created"]["direction"] == "falling"

        flat = compute_forward_outlook(
            findings_this_week=4,
            findings_last_week=4,
            escalations_this_week=0,
            escalations_last_week=0,
            needs_human_backlog=0,
        )
        assert flat["findings_created"]["direction"] == "flat"

    def test_zero_base_never_fabricates_a_percentage(self):
        result = compute_forward_outlook(
            findings_this_week=5,
            findings_last_week=0,
            escalations_this_week=0,
            escalations_last_week=0,
            needs_human_backlog=0,
        )
        assert result["findings_created"]["pct_change"] is None  # no ∞% invention

    def test_no_history_is_no_data(self):
        result = compute_forward_outlook(
            findings_this_week=0,
            findings_last_week=0,
            escalations_this_week=0,
            escalations_last_week=0,
            needs_human_backlog=0,
        )
        assert result["no_data"] is True


class TestComposePostureReport:
    def _aggregates(self):
        rows = [
            _finding(1, severity="high"),
            _finding(2, severity="high", created_hours_ago=10.0, triaged_hours_ago=9.0),
            _finding(3, severity="low", triaged_hours_ago=2.0, needs_human=True),
        ]
        findings = compute_findings_posture(rows, now=NOW, window_days=7)
        kpis = compute_response_kpis([rows[1]], window_days=7)
        fleet = compute_fleet_health(
            [{"id": "r1", "status": "completed", "cost_records": [{"cost_usd": 0.10}]}],
            [{"id": "t2", "agent": "triage_agent", "rubric_verdict": "satisfied"}],
            [{"rating": "up"}],
            window_days=7,
        )
        outlook = compute_forward_outlook(
            findings_this_week=3,
            findings_last_week=1,
            escalations_this_week=1,
            escalations_last_week=0,
            needs_human_backlog=1,
        )
        return findings, kpis, fleet, outlook

    def test_engineer_report_has_full_drilldown_with_finding_ids(self):
        report = compose_posture_report(PERSONA_ENGINEER, *self._aggregates())

        assert report["persona"] == PERSONA_ENGINEER
        assert set(report) >= {"ctem_mapping", "findings_posture", "response_kpis", "fleet_health", "forward_outlook"}
        assert "task-1" in report["findings_posture"]["open_findings"]["sample_task_ids"]
        # CTEM narrative names all four operational stages.
        assert set(report["ctem_mapping"]) == {"discovery", "prioritization", "validation", "mobilization"}

    def test_executive_report_is_nacd_shaped_without_finding_ids(self):
        import json

        report = compose_posture_report(PERSONA_EXECUTIVE, *self._aggregates())

        assert report["persona"] == PERSONA_EXECUTIVE
        nacd = report["nacd_summary"]
        assert set(nacd) == {"threat_environment", "financial", "maturity", "forward_looking"}
        # No per-finding ids anywhere in the exec lens.
        assert "task-1" not in json.dumps(report)
        assert nacd["maturity"]["benchmark_source"] == BENCHMARK_SOURCE

    def test_both_personas_carry_the_same_facts(self):
        aggregates = self._aggregates()
        engineer = compose_posture_report(PERSONA_ENGINEER, *aggregates)
        executive = compose_posture_report(PERSONA_EXECUTIVE, *aggregates)

        assert (
            executive["nacd_summary"]["threat_environment"]["open_findings_total"]
            == engineer["findings_posture"]["open_findings"]["total"]
        )
        assert (
            executive["nacd_summary"]["financial"]["total_cost_usd_window"]
            == engineer["fleet_health"]["cost"]["total_cost_usd"]
        )
        assert (
            executive["nacd_summary"]["maturity"]["rubric_pass_rate"]
            == engineer["fleet_health"]["rubric_verdicts"]["pass_rate"]
        )
        assert (
            executive["nacd_summary"]["forward_looking"]["needs_human_backlog"]
            == engineer["findings_posture"]["needs_human_backlog"]["count"]
        )

    def test_no_composite_score_anywhere(self):
        # Constitutional (vision §2.1): components only, never one blended number.
        import json

        for persona in (PERSONA_ENGINEER, PERSONA_EXECUTIVE):
            report = compose_posture_report(persona, *self._aggregates())
            assert "posture_score" not in json.dumps(report)

    def test_unknown_persona_is_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            compose_posture_report("board_member", *self._aggregates())
