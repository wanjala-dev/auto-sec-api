"""Unit tests — the daily AI-action rollup (``ai.rollup_ai_action_daily``).

Pins the recompute-not-increment contract of the ``AiActionDailyRollup``
read model: re-running a day converges on the same numbers (idempotent),
late-arriving raw rows are absorbed on the next pass (never double
counted), and the backfill management command rebuilds history including
the current partial day.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from components.agents.infrastructure.tasks.ai_action_rollup_tasks import (
    rollup_ai_action_daily,
    rollup_ai_actions_for_day,
)
from infrastructure.persistence.ai.agents.models import (
    AiActionDailyRollup,
    DeepRun,
    DeepRunLog,
)


def _make_run(workspace, user, *, status, created_at):
    run = DeepRun.objects.create(
        thread_id=f"thread-{timezone.now().timestamp()}-{DeepRun.objects.count()}",
        plan_id="plan-1",
        user=user,
        workspace=workspace,
        status=status,
    )
    DeepRun.objects.filter(pk=run.pk).update(created_at=created_at)
    return run


def _make_log(run, *, event_type, created_at, **fields):
    log = DeepRunLog.objects.create(deep_run=run, event_type=event_type, **fields)
    DeepRunLog.objects.filter(pk=log.pk).update(created_at=created_at)
    return log


@pytest.fixture
def yesterday():
    return (timezone.now() - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.mark.django_db
class TestRollupForDay:
    def test_rolls_runs_tools_tokens_and_cost_per_workspace_day(self, workspace_factory, user_factory, yesterday):
        workspace = workspace_factory()
        user = user_factory()
        completed = _make_run(workspace, user, status=DeepRun.STATUS_COMPLETED, created_at=yesterday)
        _make_run(workspace, user, status=DeepRun.STATUS_FAILED, created_at=yesterday)
        _make_run(workspace, user, status=DeepRun.STATUS_RUNNING, created_at=yesterday)
        _make_log(completed, event_type="tool_observation", created_at=yesterday, tool_name="query_logs")
        _make_log(completed, event_type="tool_observation", created_at=yesterday, tool_name="list_findings")
        _make_log(
            completed,
            event_type="llm_call",
            created_at=yesterday,
            model_used="gpt-test",
            prompt_tokens=100,
            completion_tokens=40,
            cost_usd=Decimal("0.0123"),
        )
        _make_log(
            completed,
            event_type="llm_call",
            created_at=yesterday,
            model_used="gpt-test",
            prompt_tokens=50,
            completion_tokens=10,
            cost_usd=Decimal("0.0007"),
        )

        written = rollup_ai_actions_for_day(yesterday.date())

        assert written == 1
        row = AiActionDailyRollup.objects.get(workspace=workspace, date=yesterday.date())
        assert row.runs_total == 3
        assert row.runs_completed == 1
        assert row.runs_failed == 1
        assert row.tool_calls == 2
        assert row.tokens_input == 150
        assert row.tokens_output == 50
        assert row.cost_usd == Decimal("0.013000")

    def test_rows_outside_the_day_are_excluded(self, workspace_factory, user_factory, yesterday):
        workspace = workspace_factory()
        user = user_factory()
        _make_run(workspace, user, status=DeepRun.STATUS_COMPLETED, created_at=yesterday - timedelta(days=2))

        written = rollup_ai_actions_for_day(yesterday.date())

        assert written == 0
        assert not AiActionDailyRollup.objects.filter(date=yesterday.date()).exists()

    def test_null_token_and_cost_fields_count_as_zero(self, workspace_factory, user_factory, yesterday):
        workspace = workspace_factory()
        user = user_factory()
        run = _make_run(workspace, user, status=DeepRun.STATUS_COMPLETED, created_at=yesterday)
        _make_log(run, event_type="llm_call", created_at=yesterday, model_used="gpt-test")

        rollup_ai_actions_for_day(yesterday.date())

        row = AiActionDailyRollup.objects.get(workspace=workspace, date=yesterday.date())
        assert row.tokens_input == 0
        assert row.tokens_output == 0
        assert row.cost_usd == Decimal("0")


@pytest.mark.django_db
class TestIdempotency:
    def test_rerun_converges_on_the_same_single_row(self, workspace_factory, user_factory, yesterday):
        workspace = workspace_factory()
        user = user_factory()
        _make_run(workspace, user, status=DeepRun.STATUS_COMPLETED, created_at=yesterday)

        rollup_ai_action_daily(days_back=1)
        first = AiActionDailyRollup.objects.get(workspace=workspace, date=yesterday.date())
        rollup_ai_action_daily(days_back=1)

        rows = AiActionDailyRollup.objects.filter(workspace=workspace, date=yesterday.date())
        assert rows.count() == 1
        assert rows.first().runs_total == first.runs_total == 1

    def test_late_row_is_absorbed_not_double_counted(self, workspace_factory, user_factory, yesterday):
        workspace = workspace_factory()
        user = user_factory()
        _make_run(workspace, user, status=DeepRun.STATUS_COMPLETED, created_at=yesterday)
        rollup_ai_action_daily(days_back=1)

        _make_run(workspace, user, status=DeepRun.STATUS_FAILED, created_at=yesterday)
        rollup_ai_action_daily(days_back=1)

        row = AiActionDailyRollup.objects.get(workspace=workspace, date=yesterday.date())
        assert row.runs_total == 2
        assert row.runs_failed == 1

    def test_workspaceless_runs_are_ignored(self, user_factory, yesterday):
        user = user_factory()
        _make_run(None, user, status=DeepRun.STATUS_COMPLETED, created_at=yesterday)

        written = rollup_ai_action_daily(days_back=1)

        assert written == 0


@pytest.mark.django_db
class TestBackfill:
    def test_backfill_covers_n_days_including_today(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        user = user_factory()
        now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        for offset in range(3):
            _make_run(
                workspace,
                user,
                status=DeepRun.STATUS_COMPLETED,
                created_at=now - timedelta(days=offset),
            )

        call_command("backfill_ai_action_rollups", "--days", "3")

        dates = set(AiActionDailyRollup.objects.filter(workspace=workspace).values_list("date", flat=True))
        expected = {(now - timedelta(days=offset)).date() for offset in range(3)}
        assert dates == expected

    def test_backfill_is_rerunnable(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        user = user_factory()
        now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        _make_run(workspace, user, status=DeepRun.STATUS_COMPLETED, created_at=now)

        call_command("backfill_ai_action_rollups", "--days", "2")
        call_command("backfill_ai_action_rollups", "--days", "2")

        assert AiActionDailyRollup.objects.filter(workspace=workspace).count() == 1
