"""The rollup → endpoint pipeline actually carries numbers end to end.

The beat entry added in ADR 0032 Phase 1 is asserted statically by
``tests/architecture/test_celery_beat_registration.py``. This file asserts the
other half: that when the task DOES run, the endpoint stops returning zeros.
A scheduled task writing to tables nobody reads, or a reader pointed at tables
nobody writes, both look exactly like this pipeline working — so the join is
tested rather than assumed.

Also pins the two properties the rollup must keep as it is now run every hour:
it recomputes rather than increments (re-running a day converges instead of
doubling), and it never attributes a run to a workspace that did not make it.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from components.agents.infrastructure.tasks.ai_quality_rollup_tasks import (
    rollup_ai_quality_daily,
)
from components.shared_kernel.domain.measured_rate import STATE_MEASURED, STATE_NO_DATA
from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog
from infrastructure.persistence.ai.aggregations.models import (
    AIModelDailyMetric,
    AIWorkspaceDailyMetric,
)

URL = "/ai/agents/runs/analytics/overview/"


@pytest.fixture
def roles(db):
    call_command("seed_workspace_roles")


def _run(workspace, user, *, status=DeepRun.STATUS_COMPLETED):
    return DeepRun.objects.create(
        thread_id=str(uuid.uuid4()),
        plan_id=str(uuid.uuid4()),
        user=user,
        workspace=workspace,
        status=status,
        state={},
    )


def _llm_call(run, *, model="gpt-4o-mini", latency=900, cost="0.002000"):
    return DeepRunLog.objects.create(
        deep_run=run,
        event_type="llm_call",
        agent_type="planner",
        model_used=model,
        prompt_tokens=400,
        completion_tokens=120,
        latency_ms=latency,
        cost_usd=Decimal(cost),
        prompt_id="planner.system",
        prompt_version="v12",
    )


@pytest.mark.django_db
class TestTheRollupFillsWhatTheEndpointReads:
    def test_before_the_rollup_the_panel_says_not_measured(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        """Exactly the production state the missing beat entry produced."""
        workspace = workspace_factory()
        analyst = user_factory()
        team_factory(workspace=workspace, members=[analyst])
        api_client.force_authenticate(analyst)
        _llm_call(_run(workspace, analyst))

        body = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 7}).json()

        # Raw telemetry exists; the read model is empty because nothing rolled
        # it up. The panel must say so rather than show a clean zero.
        assert body["coverage"]["state"] == STATE_NO_DATA
        assert body["totals"]["llm_calls"] == 0

    def test_after_the_rollup_the_panel_carries_the_real_numbers(
        self, roles, api_client, workspace_factory, user_factory, team_factory
    ):
        workspace = workspace_factory()
        analyst = user_factory()
        team_factory(workspace=workspace, members=[analyst])
        api_client.force_authenticate(analyst)
        run = _run(workspace, analyst)
        _llm_call(run, latency=500)
        _llm_call(run, latency=2500)
        _run(workspace, analyst, status=DeepRun.STATUS_FAILED)

        rollup_ai_quality_daily(days_back=1)
        body = api_client.get(URL, {"workspace_id": str(workspace.id), "days": 7}).json()

        assert body["coverage"]["state"] == STATE_MEASURED
        assert body["totals"]["llm_calls"] == 2
        assert body["totals"]["runs_total"] == 2
        assert body["totals"]["runs_failed"] == 1
        assert body["totals"]["by_model"][0]["model"] == "gpt-4o-mini"
        assert Decimal(body["totals"]["cost_usd"]) == Decimal("0.004000")
        # Two runs is well under the floor: a 50% failure rate off n=2 must
        # never present as measured.
        assert body["totals"]["rates"]["failure"]["state"] != STATE_MEASURED
        assert body["totals"]["rates"]["failure"]["trials"] == 2

    def test_rerunning_the_rollup_converges_rather_than_doubling(self, workspace_factory, user_factory):
        """Hourly beat means the same day is recomputed ~24 times."""
        workspace = workspace_factory()
        analyst = user_factory()
        _llm_call(_run(workspace, analyst))

        rollup_ai_quality_daily(days_back=1)
        first = AIModelDailyMetric.objects.get(workspace=workspace)
        rollup_ai_quality_daily(days_back=1)
        second = AIModelDailyMetric.objects.get(workspace=workspace)

        assert first.llm_calls == second.llm_calls == 1
        assert AIWorkspaceDailyMetric.objects.filter(workspace=workspace).count() == 1

    def test_a_run_with_no_workspace_enters_no_workspaces_totals(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        analyst = user_factory()
        orphan = DeepRun.objects.create(
            thread_id=str(uuid.uuid4()),
            plan_id=str(uuid.uuid4()),
            user=analyst,
            workspace=None,
            status=DeepRun.STATUS_COMPLETED,
            state={},
        )
        _llm_call(orphan)

        rollup_ai_quality_daily(days_back=1)

        assert AIWorkspaceDailyMetric.objects.filter(workspace=workspace).count() == 0
        assert AIModelDailyMetric.objects.filter(workspace=workspace).count() == 0

    def test_one_workspaces_telemetry_never_lands_in_anothers_rollup(self, workspace_factory, user_factory):
        mine = workspace_factory()
        theirs = workspace_factory()
        analyst = user_factory()
        _llm_call(_run(theirs, analyst), model="their-model")

        rollup_ai_quality_daily(days_back=1)

        assert not AIModelDailyMetric.objects.filter(workspace=mine).exists()
        assert AIModelDailyMetric.objects.filter(workspace=theirs, model_used="their-model").exists()

    def test_a_stale_day_outside_the_window_is_left_alone(self, workspace_factory, user_factory):
        """A 2-day window must not delete rollups it did not recompute."""
        workspace = workspace_factory()
        old = AIWorkspaceDailyMetric.objects.create(
            workspace=workspace,
            date=timezone.now().date() - timedelta(days=30),
            runs_total=7,
        )

        rollup_ai_quality_daily(days_back=2)

        old.refresh_from_db()
        assert old.runs_total == 7
