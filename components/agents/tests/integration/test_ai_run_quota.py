"""Metered-AI quota — adapter counting + tier resolution (P3, unified storage).

Exercises ``AiRunQuotaAdapter`` against a real DB. The run tally lives on the
shared ``WorkspaceAIUsage`` row (``monthly_runs_used``, own monthly window) —
recorded via ``record_run`` and read back through the tier cap resolved from
``EntitlementsResolver``. Premium (empty limits) is unlimited.
"""
from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.ai_run_quota_adapter import (
    AiRunQuotaAdapter,
)


def _plan(title: str, ai_cap: int | None):
    from infrastructure.persistence.subscription.models import Plan

    limits = {} if ai_cap is None else {"max_ai_runs_per_month": ai_cap}
    return Plan.objects.create(title=title, limits=limits, price=0)


@pytest.mark.django_db
class TestAiRunQuotaAdapter:
    def test_free_workspace_allows_until_cap_then_blocks(self, user_factory, workspace_factory):
        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Free", 2)
        ws.save(update_fields=["plan"])
        adapter = AiRunQuotaAdapter()

        # Fresh month — nothing used yet.
        s0 = adapter.check_for_workspace(str(ws.id))
        assert (s0.allowed, s0.used, s0.limit) == (True, 0, 2)

        adapter.record_run(str(ws.id))
        s1 = adapter.check_for_workspace(str(ws.id))
        assert (s1.allowed, s1.used) == (True, 1)

        adapter.record_run(str(ws.id))
        s2 = adapter.check_for_workspace(str(ws.id))
        # Used 2 of 2 — the next run is blocked.
        assert (s2.allowed, s2.used, s2.limit) == (False, 2, 2)

    def test_premium_empty_limits_is_unlimited(self, user_factory, workspace_factory):
        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Premium", None)
        ws.save(update_fields=["plan"])
        adapter = AiRunQuotaAdapter()

        for _ in range(5):
            adapter.record_run(str(ws.id))
        status = adapter.check_for_workspace(str(ws.id))
        assert status.is_unlimited is True
        assert status.allowed is True
        assert status.used == 5  # still reported for observability

    def test_workspace_override_beats_plan_limit(self, user_factory, workspace_factory):
        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Free", 2)
        ws.entitlement_overrides = {"max_ai_runs_per_month": 10}
        ws.save(update_fields=["plan", "entitlement_overrides"])
        adapter = AiRunQuotaAdapter()

        for _ in range(3):
            adapter.record_run(str(ws.id))
        status = adapter.check_for_workspace(str(ws.id))
        assert status.limit == 10
        assert status.allowed is True

    def test_no_plan_workspace_is_unlimited(self, user_factory, workspace_factory):
        ws = workspace_factory(owner=user_factory())  # no plan assigned
        status = AiRunQuotaAdapter().check_for_workspace(str(ws.id))
        assert status.limit is None
        assert status.allowed is True

    def test_falsy_workspace_fails_open(self):
        status = AiRunQuotaAdapter().check_for_workspace(None)
        assert status.allowed is True
        assert status.limit is None

    def test_check_for_agent_resolves_workspace(self, user_factory, workspace_factory):
        from infrastructure.persistence.ai.agents.models import Agent

        user = user_factory()
        ws = workspace_factory(owner=user)
        ws.plan = _plan("Free", 1)
        ws.save(update_fields=["plan"])
        agent = Agent.objects.create(user=user, workspace=ws, agent_type="task_agent")

        adapter = AiRunQuotaAdapter()
        adapter.record_run(str(ws.id))
        status = adapter.check_for_agent(str(agent.pk))
        assert status.workspace_id == str(ws.id)
        assert (status.allowed, status.used, status.limit) == (False, 1, 1)

    def test_check_for_unknown_agent_fails_open(self):
        import uuid

        status = AiRunQuotaAdapter().check_for_agent(str(uuid.uuid4()))
        assert status.allowed is True
        assert status.limit is None

    def test_record_run_is_workspace_scoped(self, user_factory, workspace_factory):
        ws_a = workspace_factory(owner=user_factory())
        ws_b = workspace_factory(owner=user_factory())
        adapter = AiRunQuotaAdapter()

        adapter.record_run(str(ws_a.id))
        adapter.record_run(str(ws_a.id))

        assert adapter.check_for_workspace(str(ws_a.id)).used == 2
        assert adapter.check_for_workspace(str(ws_b.id)).used == 0


@pytest.mark.django_db
class TestRunsSurfacedInQuotaSnapshot:
    """me/summary's AI-quota snapshot carries the run dimension (one meter)."""

    def test_snapshot_includes_runs_remaining(self, user_factory, workspace_factory):
        from components.agents.application.providers.workspace_ai_config_provider import (
            get_workspace_ai_config_provider,
        )
        from components.agents.application.queries.workspace_ai_quota_query import (
            build_workspace_ai_quota_snapshot,
        )

        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Free", 20)
        ws.save(update_fields=["plan"])
        AiRunQuotaAdapter().record_run(str(ws.id))

        snapshot = build_workspace_ai_quota_snapshot(
            str(ws.id),
            ai_config_port=get_workspace_ai_config_provider().get_port(),
            ai_run_quota_port=AiRunQuotaAdapter(),
        )
        assert snapshot["monthly_run_budget"] == 20
        assert snapshot["monthly_runs_used"] == 1
        assert snapshot["monthly_runs_remaining"] == 19

    def test_unlimited_tier_runs_remaining_is_minus_one(self, user_factory, workspace_factory):
        from components.agents.application.providers.workspace_ai_config_provider import (
            get_workspace_ai_config_provider,
        )
        from components.agents.application.queries.workspace_ai_quota_query import (
            build_workspace_ai_quota_snapshot,
        )

        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Premium", None)
        ws.save(update_fields=["plan"])

        snapshot = build_workspace_ai_quota_snapshot(
            str(ws.id),
            ai_config_port=get_workspace_ai_config_provider().get_port(),
            ai_run_quota_port=AiRunQuotaAdapter(),
        )
        assert snapshot["monthly_run_budget"] == 0  # 0 == unlimited convention
        assert snapshot["monthly_runs_remaining"] == -1


@pytest.mark.django_db
class TestExecuteEndpointReturns402WhenOverLimit:
    def test_execute_over_limit_returns_402_with_upgrade_nudge(
        self, api_client, user_factory, workspace_factory
    ):
        from django.urls import reverse

        from infrastructure.persistence.ai.agents.models import Agent

        user = user_factory()
        ws = workspace_factory(owner=user)
        ws.plan = _plan("Free", 1)
        ws.save(update_fields=["plan"])
        agent = Agent.objects.create(
            agent_type="sponsorship_agent", user=user, workspace=ws, status="active", config={}
        )
        # Burn the single allowed run for this month.
        AiRunQuotaAdapter().record_run(str(ws.id))

        api_client.force_authenticate(user=user)
        url = reverse("agents:agent-execute", args=[str(agent.agent_id)])
        response = api_client.post(url, {"query": "do something"}, format="json")

        assert response.status_code == 402
        body = response.json()
        assert body["code"] == "ai_run_limit_exceeded"
        assert body["used"] == 1 and body["limit"] == 1
        assert body["upgrade_required"] is True
