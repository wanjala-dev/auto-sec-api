"""The AI-quality panel must never read green because nothing ran.

ADR 0032 D3 / D4 / D8. Three properties, each of which has an existing incident
behind it:

* **Absence is a distinct state.** #415 shipped a report that read clean because
  nothing had been scanned. The same shape was waiting here: the endpoint
  returned a fully-formed payload of zeros — 0 failures, $0 cost, 0 votes —
  whether the workspace ran a hundred agents or none, because the rollup task
  that fills those tables was in no beat schedule.
* **Every rate carries n and a bound.** "3 of 4 = 75%" is the number that gets
  put in a deck. ``totals.rates`` carries the denominator and the 95% Wilson
  interval; the bare ratios are retained only for contract stability.
* **What was dropped is stated.** ``DeepRun.workspace`` is nullable, so a run
  with no attribution is invisible to every workspace's totals. The panel says
  how many rather than absorbing them.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from components.shared_kernel.domain.measured_rate import (
    STATE_MEASURED,
    STATE_NO_DATA,
    STATE_TOO_FEW,
)
from infrastructure.persistence.ai.agents.models import DeepRun
from infrastructure.persistence.ai.aggregations.models import (
    AIModelDailyMetric,
    AIWorkspaceDailyMetric,
)

URL = "/ai/agents/runs/analytics/overview/"


@pytest.fixture
def roles(db):
    call_command("seed_workspace_roles")


def _teammate(api_client, workspace, user_factory, team_factory):
    analyst = user_factory()
    team_factory(workspace=workspace, members=[analyst])
    api_client.force_authenticate(analyst)
    return analyst


def _day_row(workspace, *, offset=0, runs_total=0, runs_failed=0, up=0, down=0, messages=0):
    return AIWorkspaceDailyMetric.objects.create(
        workspace=workspace,
        date=timezone.now().date() - timedelta(days=offset),
        runs_total=runs_total,
        runs_completed=max(0, runs_total - runs_failed),
        runs_failed=runs_failed,
        assistant_messages=messages,
        feedback_up=up,
        feedback_down=down,
    )


def _model_row(workspace, *, offset=0, model="gpt-4o-mini", calls=5):
    return AIModelDailyMetric.objects.create(
        workspace=workspace,
        date=timezone.now().date() - timedelta(days=offset),
        model_used=model,
        llm_calls=calls,
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=Decimal("0.010000"),
        latency_p50_ms=800,
        latency_p95_ms=2400,
    )


@pytest.mark.django_db
class TestAbsenceIsNotAGoodResult:
    def test_an_empty_window_says_not_measured_rather_than_zero_percent(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        """The exact defect the unscheduled rollup produced in production."""
        workspace = workspace_factory()
        _teammate(api_client, workspace, user_factory, team_factory)

        body = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 30}).json()

        assert body["coverage"]["state"] == STATE_NO_DATA
        assert "Not measured" in body["coverage"]["summary"]
        # A failure rate of "0" would read as "nothing ever failed".
        assert body["totals"]["rates"]["failure"]["state"] == STATE_NO_DATA
        assert body["totals"]["rates"]["failure"]["point"] is None
        assert body["totals"]["rates"]["feedback_positive"]["state"] == STATE_NO_DATA

    def test_a_day_nothing_happened_is_flagged_no_data(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        _teammate(api_client, workspace, user_factory, team_factory)
        _day_row(workspace, offset=0, runs_total=4, runs_failed=1)

        body = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 7}).json()

        by_state = {day["date"]: day["state"] for day in body["series"]}
        today = timezone.now().date().isoformat()
        assert by_state[today] == STATE_MEASURED
        # Six quiet days: emitted for a continuous axis, but not as zero bars
        # that read as "no failures".
        assert sum(1 for state in by_state.values() if state == STATE_NO_DATA) == 6

    def test_activity_flips_coverage_to_measured(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        _teammate(api_client, workspace, user_factory, team_factory)
        _day_row(workspace, runs_total=12, runs_failed=2)
        _model_row(workspace)

        body = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 30}).json()

        assert body["coverage"]["state"] == STATE_MEASURED
        assert body["coverage"]["runs_total"] == 12
        assert body["coverage"]["days_with_activity"] == 1


@pytest.mark.django_db
class TestSmallSamplesDoNotDeceive:
    def test_three_of_four_is_reported_with_n_and_a_bound(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        """The "3 of 4 = 75%" failure mode, refused explicitly."""
        workspace = workspace_factory()
        _teammate(api_client, workspace, user_factory, team_factory)
        _day_row(workspace, runs_total=4, runs_failed=1, up=3, down=1, messages=4)

        totals = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 30}).json()["totals"]

        positive = totals["rates"]["feedback_positive"]
        assert positive["state"] == STATE_TOO_FEW
        assert positive["observed"] == 3
        assert positive["trials"] == 4  # the DENOMINATOR travels with the number
        assert positive["lower_bound"] < 0.75  # never the bare point estimate
        assert "too few" in positive["summary"]

    def test_enough_runs_reaches_measured_and_still_carries_bounds(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        _teammate(api_client, workspace, user_factory, team_factory)
        _day_row(workspace, runs_total=40, runs_failed=4, up=20, down=2, messages=40)

        rates = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 30}).json()["totals"]["rates"]

        assert rates["failure"]["state"] == STATE_MEASURED
        assert rates["failure"]["trials"] == 40
        assert rates["feedback_positive"]["state"] == STATE_MEASURED

    def test_a_clean_streak_is_not_reported_as_a_zero_failure_rate(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        """Rule of three: 0 failures in 12 runs is not "never fails"."""
        workspace = workspace_factory()
        _teammate(api_client, workspace, user_factory, team_factory)
        _day_row(workspace, runs_total=12, runs_failed=0)

        failure = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 30}).json()["totals"]["rates"][
            "failure"
        ]

        assert failure["observed"] == 0
        assert failure["upper_bound"] > 0.15


@pytest.mark.django_db
class TestExclusionsAreStated:
    def test_runs_with_no_workspace_are_counted_not_absorbed(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        analyst = _teammate(api_client, workspace, user_factory, team_factory)
        DeepRun.objects.create(
            thread_id=str(uuid.uuid4()),
            plan_id=str(uuid.uuid4()),
            user=analyst,
            workspace=None,
            status=DeepRun.STATUS_COMPLETED,
            state={},
        )

        body = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 30}).json()

        assert body["excluded"]["unattributed_runs"] == 1
        assert body["excluded"]["sample_rows"] == 0

    def test_another_workspaces_rollups_never_appear(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        mine = workspace_factory()
        theirs = workspace_factory()
        _teammate(api_client, mine, user_factory, team_factory)
        _day_row(theirs, runs_total=99, runs_failed=50)
        _model_row(theirs, model="leaky-model")

        body = api_client.get(URL, {"workspace_id": str(mine.id), "days": 30}).json()

        assert body["totals"]["runs_total"] == 0
        assert body["totals"]["by_model"] == []
        assert body["coverage"]["state"] == STATE_NO_DATA


@pytest.mark.django_db
class TestContractStability:
    def test_the_established_keys_are_all_still_present(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        """The frontend panel is built against these — additions only."""
        workspace = workspace_factory()
        _teammate(api_client, workspace, user_factory, team_factory)
        _day_row(workspace, runs_total=3, runs_failed=1, up=1, down=1, messages=3)
        _model_row(workspace)

        body = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 30}).json()

        assert {"workspace_id", "window_days", "series", "totals", "model_changes"} <= set(body)
        assert {
            "llm_calls",
            "cost_usd",
            "runs_total",
            "runs_failed",
            "failure_rate",
            "assistant_messages",
            "feedback_up",
            "feedback_down",
            "positive_ratio",
            "feedback_rate",
            "by_model",
        } <= set(body["totals"])
        day = body["series"][-1]
        assert {
            "date",
            "models",
            "runs_total",
            "runs_completed",
            "runs_failed",
            "assistant_messages",
            "feedback_up",
            "feedback_down",
        } <= set(day)
        assert {
            "model",
            "llm_calls",
            "prompt_tokens",
            "completion_tokens",
            "cost_usd",
            "latency_p50_ms",
            "latency_p95_ms",
        } <= set(day["models"][0])
