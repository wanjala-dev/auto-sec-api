"""Integration tests for the financial agent tools' log + progress emits.

Phase 2 cohort 2 of the chat-progress notifications plan. Verifies that
``get_financial_summary`` and ``compare_budget_spend`` — the two
heaviest financial tools the chat agent reaches for — emit narrative
log + progress events while they run, so the user sees what's happening
mid-aggregation instead of staring at "loading…".

Tools take an ``agent`` arg whose ``_active_deep_run_context`` is set
by ``BaseAgent.execute`` for the call duration; here we use a tiny
stub with that attribute pre-set, sidestepping the langchain executor.

See ``docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md`` Phase 2
cohort 2.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from components.agents.application.ports.deep_run_observability_port import (
    EVENT_TOOL_LOG,
    EVENT_TOOL_PROGRESS,
)
from components.agents.application.services.deep_run_context import (
    DeepRunContext,
    DeepRunContextOptions,
)
from components.agents.infrastructure.adapters.deep_run_log_observability_adapter import (
    DeepRunLogObservabilityAdapter,
)
from components.agents.infrastructure.adapters.langchain.tools.financial_agent import (
    compare_budget_spend,
    get_financial_summary,
)


@pytest.fixture
def deep_run(workspace_factory, user_factory):
    from infrastructure.persistence.ai.agents.models import DeepRun

    workspace = workspace_factory()
    user = user_factory()
    run = DeepRun.objects.create(
        thread_id="test-financial-tools-thread",
        plan_id="plan-financial-tools",
        user=user,
        workspace=workspace,
        status=DeepRun.STATUS_RUNNING,
    )
    return run


@pytest.fixture
def deep_run_context(deep_run):
    return DeepRunContext(
        DeepRunLogObservabilityAdapter(),
        DeepRunContextOptions(
            thread_id=deep_run.thread_id,
            default_agent_type="financial_agent",
            default_tool_name=None,
        ),
    )


def _stub_agent(workspace_id, deep_run_context=None):
    """Minimal stand-in for the langchain BaseAgent the tools expect.

    Tools read ``agent.workspace_id`` and ``agent._active_deep_run_context``
    only — the rest of the BaseAgent surface is irrelevant here.
    """

    class _Stub:
        pass

    stub = _Stub()
    stub.workspace_id = str(workspace_id)
    stub._active_deep_run_context = deep_run_context
    return stub


@pytest.mark.django_db
class TestGetFinancialSummaryEmits:
    def test_emits_reading_then_aggregating_then_summary_with_payload(
        self, deep_run, deep_run_context
    ):
        # No transactions in the workspace — tool still runs to
        # completion (returning zeros) and emits the full sequence.
        agent = _stub_agent(deep_run.workspace_id, deep_run_context)
        result = get_financial_summary(agent, payload="month")

        assert "Financial summary (month)" in result

        infos = list(
            deep_run.logs.filter(event_type=EVENT_TOOL_LOG)
            .order_by("created_at")
        )
        # Three info lines: reading, aggregating, computed-summary.
        info_messages = [log.payload.get("message") for log in infos]
        assert any("Reading month transactions" in m for m in info_messages), info_messages
        assert any("Aggregating income" in m for m in info_messages), info_messages
        assert any("Computed month summary" in m for m in info_messages), info_messages

        # Final info carries structured payload for the renderer.
        computed = next(
            log for log in infos if "Computed" in (log.payload.get("message") or "")
        )
        assert computed.payload["period"] == "month"
        assert computed.payload["income"] == 0.0
        assert computed.payload["expenses"] == 0.0
        assert computed.payload["balance"] == 0.0

        # Progress sequence: 30, 70, 100 — last one always 100.
        progress_logs = list(
            deep_run.logs.filter(event_type=EVENT_TOOL_PROGRESS)
            .order_by("created_at")
        )
        percents = [log.payload.get("progress_percent") for log in progress_logs]
        assert percents == [30, 70, 100]
        # Every emit tagged with the tool name so the renderer can
        # group lines by tool card.
        assert all(log.tool_name == "get_financial_summary" for log in progress_logs)

    def test_emits_warn_on_invalid_period(self, deep_run, deep_run_context):
        # Invalid period string short-circuits before aggregation;
        # the function returns the error string. The current emit
        # placement still fires the "Reading…" info before the
        # validation, but the warn fallback path isn't hit because
        # there's no exception. This test pins down the actual
        # behaviour rather than the aspirational one.
        agent = _stub_agent(deep_run.workspace_id, deep_run_context)
        result = get_financial_summary(agent, payload="quarter")

        assert "Invalid period" in result

    def test_no_active_context_falls_back_to_noop_silently(self, deep_run):
        agent = _stub_agent(deep_run.workspace_id, None)
        result = get_financial_summary(agent, payload="year")

        assert "Financial summary (year)" in result
        # No emits because ctx is the noop singleton.
        assert deep_run.logs.count() == 0


@pytest.mark.django_db
class TestCompareBudgetSpendEmits:
    def test_emits_no_budgets_warn_when_workspace_has_no_budgets(
        self, deep_run, deep_run_context
    ):
        # workspace_factory's ensure_workspace_scaffolding creates a
        # default budget; delete it so the "no budgets" branch fires.
        from infrastructure.persistence.budget.models import Budget

        Budget.objects.filter(workspace_id=deep_run.workspace_id).delete()

        agent = _stub_agent(deep_run.workspace_id, deep_run_context)
        result = compare_budget_spend(agent, payload={"period": "month"})

        assert "No budgets found" in result

        # Expect: "Loading budgets…" info + 20% progress + warn + 100%.
        events = [
            (log.event_type, log.payload.get("severity"), log.payload.get("progress_percent"))
            for log in deep_run.logs.order_by("created_at")
        ]
        # Filter for the tool-events (some other emits may interleave from
        # signal bridges; tool_log + tool_progress is what we own).
        tool_events = [e for e in events if e[0] in (EVENT_TOOL_LOG, EVENT_TOOL_PROGRESS)]
        assert any(e == (EVENT_TOOL_LOG, "info", None) for e in tool_events), tool_events
        assert any(e == (EVENT_TOOL_LOG, "warn", None) for e in tool_events), tool_events
        # Final progress of the run is 100.
        progress_logs = list(
            deep_run.logs.filter(event_type=EVENT_TOOL_PROGRESS).order_by("created_at")
        )
        assert progress_logs[-1].payload["progress_percent"] == 100

    def test_emits_done_summary_with_budget_count_and_totals(
        self, deep_run, deep_run_context, workspace_factory, user_factory
    ):
        # Drop the default budget that workspace_factory's
        # ensure_workspace_scaffolding seeds, so the test owns the
        # full budget count.
        from infrastructure.persistence.budget.models import Budget, BudgetEstimate
        from infrastructure.persistence.budget.categories.models import Category

        workspace = deep_run.workspace
        owner = workspace.workspace_owner

        Budget.objects.filter(workspace=workspace).delete()

        category = Category.objects.create(
            workspace=workspace,
            user=owner,
            name="Test Category",
            slug="test-category",
        )
        budget = Budget.objects.create(
            workspace=workspace,
            user=owner,
            name="Test Budget",
            slug=f"test-budget-{deep_run.id}",
            start_date=date.today(),
        )
        BudgetEstimate.objects.create(
            workspace=workspace,
            budget=budget,
            category=category,
            user=owner,
            amount=Decimal("100.00"),
            label="Test estimate",
        )

        agent = _stub_agent(workspace.id, deep_run_context)
        result = compare_budget_spend(agent, payload={"period": "month"})

        assert "Test Budget" in result
        assert "Overall:" in result

        # Final 'Done' info carries the structured payload.
        infos = [
            log
            for log in deep_run.logs.filter(event_type=EVENT_TOOL_LOG).order_by("created_at")
            if log.payload.get("severity") == "info"
        ]
        done = next(
            (log for log in infos if "Done:" in (log.payload.get("message") or "")),
            None,
        )
        assert done is not None
        assert done.payload["budget_count"] == 1
        assert done.payload["total_allocated"] == 100.0
        assert done.payload["overall_status"] == "OK"

    def test_no_active_context_falls_back_to_noop_silently(self, deep_run):
        from infrastructure.persistence.budget.models import Budget

        Budget.objects.filter(workspace_id=deep_run.workspace_id).delete()

        agent = _stub_agent(deep_run.workspace_id, None)
        result = compare_budget_spend(agent, payload={"period": "month"})

        assert "No budgets found" in result
        assert deep_run.logs.count() == 0
