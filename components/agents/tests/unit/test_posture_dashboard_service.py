"""Unit tests — posture-dashboard composition (pure, no DB).

Pins the vision-doc hard rules on the HUD POSTURE read model:

* chart series are zero-filled over the calendar window (continuous
  charts) while ``no_data`` stays honest (True only when the source had
  no rows at all);
* cost projections are ``None`` when there is nothing to project from —
  never a fabricated zero-burn claim;
* NO composite posture score anywhere in the payload;
* persona lenses share the same facts — engineer carries sample ids,
  executive (NACD shape) carries none;
* every block is action-linked (``link`` hints present).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from components.agents.application.services import ai_governance_service, posture_service
from components.agents.application.services.posture_dashboard_service import (
    compose_dashboard,
    compute_cost_projections,
    compute_daily_series,
)
from components.shared_kernel.domain.errors import ValidationError

TODAY = date(2026, 7, 20)
NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
WINDOW = 7


def _compose(persona="engineer", **overrides):
    kwargs = {
        "window_days": WINDOW,
        "today": TODAY,
        "log_lines_by_date": {},
        "log_rows_present": False,
        "findings_created_by_date": {},
        "findings_rows_present": False,
        "rollup_runs_by_date": {},
        "rollup_cost_by_date": {},
        "rollup_rows_present": False,
        "findings": posture_service.compute_findings_posture([], now=NOW, window_days=WINDOW),
        "kpis": posture_service.compute_response_kpis([], window_days=WINDOW),
        "fleet": posture_service.compute_fleet_health([], [], [], window_days=WINDOW),
        "outlook": posture_service.compute_forward_outlook(
            findings_this_week=0,
            findings_last_week=0,
            escalations_this_week=0,
            escalations_last_week=0,
            needs_human_backlog=0,
        ),
        "activity": ai_governance_service.compute_ai_activity([], [], now=NOW, window_days=WINDOW),
    }
    kwargs.update(overrides)
    return compose_dashboard(persona, **kwargs)


class TestDailySeries:
    def test_zero_fills_every_calendar_day_in_the_window(self):
        series = compute_daily_series({"2026-07-18": 5}, today=TODAY, window_days=WINDOW, link={"panel": "kanban"})
        assert len(series["points"]) == WINDOW
        assert series["points"][0]["date"] == "2026-07-14"
        assert series["points"][-1]["date"] == "2026-07-20"
        by_date = {p["date"]: p["value"] for p in series["points"]}
        assert by_date["2026-07-18"] == 5
        assert by_date["2026-07-15"] == 0
        assert series["total"] == 5
        assert series["link"] == {"panel": "kanban"}

    def test_no_data_is_true_only_when_source_had_no_rows(self):
        empty = compute_daily_series({}, today=TODAY, window_days=WINDOW, link={"panel": "logs"})
        assert empty["no_data"] is True
        real_zeroes = compute_daily_series({"2026-07-19": 0}, today=TODAY, window_days=WINDOW, link={"panel": "logs"})
        assert real_zeroes["no_data"] is False


class TestCostProjections:
    def test_projects_weekly_and_monthly_off_the_daily_average(self):
        result = compute_cost_projections(7.0, window_days=7, no_data=False)
        assert result["projected_weekly_usd"] == 7.0
        assert result["projected_monthly_usd"] == 30.0

    def test_empty_window_projects_none_not_zero(self):
        result = compute_cost_projections(0.0, window_days=7, no_data=True)
        assert result["projected_weekly_usd"] is None
        assert result["projected_monthly_usd"] is None


class TestComposeDashboard:
    def test_no_composite_score_anywhere(self):
        payload = json.dumps(_compose("engineer")) + json.dumps(_compose("executive"))
        assert "posture_score" not in payload
        assert "composite" not in payload
        assert "overall_score" not in payload

    def test_engineer_carries_sample_ids_executive_does_not(self):
        finding_rows = [
            {
                "id": "task-1",
                "severity": "high",
                "kind": "ai.logwatch",
                "status": "todo",
                "created_at": NOW,
                "triage_status": None,
                "triaged_at": None,
                "needs_human": False,
            }
        ]
        findings = posture_service.compute_findings_posture(finding_rows, now=NOW, window_days=WINDOW)
        engineer = _compose("engineer", findings=findings)
        executive = _compose("executive", findings=findings)

        assert engineer["posture"]["findings_posture"]["open_findings"]["sample_task_ids"] == ["task-1"]
        assert "nacd_summary" in executive["posture"]
        executive_json = json.dumps(executive)
        assert "sample_task_ids" not in executive_json
        assert "sample_run_ids" not in executive_json
        # Same facts, different framing.
        assert (
            executive["posture"]["nacd_summary"]["threat_environment"]["open_findings_total"]
            == engineer["posture"]["findings_posture"]["open_findings"]["total"]
            == 1
        )

    def test_executive_activity_drops_run_ids_but_keeps_counts(self):
        run_rows = [{"id": "run-1", "status": "completed", "source": "chat"}]
        activity = ai_governance_service.compute_ai_activity(run_rows, [], now=NOW, window_days=WINDOW)
        engineer = _compose("engineer", activity=activity)
        executive = _compose("executive", activity=activity)

        assert engineer["governance_activity"]["runs"]["sample_run_ids"] == ["run-1"]
        assert "sample_run_ids" not in executive["governance_activity"]["runs"]
        assert executive["governance_activity"]["runs"]["total"] == 1

    def test_every_block_is_action_linked(self):
        result = _compose("engineer")
        for series in result["series"].values():
            assert series["link"]["panel"]
        assert result["kpi_bands"]["link"] == {"panel": "kanban"}
        assert result["governance_activity"]["link"] == {"panel": "agents"}
        for link in result["links"].values():
            assert link["panel"]

    def test_kpi_bands_carry_benchmarks_and_ctem_strip_present(self):
        result = _compose("engineer")
        bands = result["kpi_bands"]["triage_latency_by_severity"]
        assert set(bands) == {"critical", "high", "medium", "low"}
        assert bands["critical"]["band_hours"] == 1.0
        assert bands["critical"]["no_data"] is True
        assert set(result["ctem_mapping"]) == {
            "discovery",
            "prioritization",
            "validation",
            "mobilization",
        }

    def test_cost_series_shape(self):
        result = _compose(
            "engineer",
            rollup_cost_by_date={"2026-07-19": 0.5, "2026-07-18": 0.2},
            rollup_rows_present=True,
        )
        cost = result["series"]["ai_cost_per_day"]
        assert cost["total_usd"] == 0.7
        assert cost["no_data"] is False
        assert cost["projected_weekly_usd"] == round(0.7 / 7 * 7, 6)
        assert cost["projected_monthly_usd"] == round(0.7 / 7 * 30, 6)

    def test_invalid_persona_raises_validation_error(self):
        with pytest.raises(ValidationError):
            _compose("board-member")
