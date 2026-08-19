"""Every new workspace is bound to the default (Free) subscription tier.

Regression cover for the billing hole found by the 2026-08-18 QA sweep: a
workspace created through either real signup path landed with
``Workspace.plan = NULL``. ``EntitlementsResolver`` treats an absent plan as
UNLIMITED (the documented ``None`` sentinel), so the metered-AI paywall — the
only enforced paid entitlement — never fired for a real customer: Free was
strictly more generous than Pro (200/month).

The gate itself was correct; the *binding* was missing. ``ensure_subscription_plans``
had been stubbed to a no-op by the fork strip and the "assign the Free plan if
the workspace has none" step promised by ``CreateWorkspaceUseCase``'s docstring
was never implemented.

Both creation paths are covered here because both are real:
  * ``POST /workspaces/create/``            → ``CreateWorkspaceUseCase``
  * onboarding bootstrap (first login/hydration) → identity's workspace adapter
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from components.subscription.domain.entitlements import EntitlementKey
from infrastructure.persistence.subscription.models import Plan
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

WORKSPACE_CREATE_URL = "/workspaces/create/"

# Free's canonical monthly AI-run allowance (TIER_CATALOG). Asserted as a
# number on purpose: the point of the test is that a real cap is bound, and a
# silent drift back to "unlimited" must fail here.
FREE_AI_RUNS = 20


class _StubAiConfigPort:
    """Minimal ``WorkspaceAIConfigPort`` stand-in — fixed run tally."""

    def __init__(self, used: int) -> None:
        self._used = used

    def get_workspace_runs_this_month(self, workspace_id: str) -> int:
        return self._used

    def record_workspace_run(self, workspace_id: str) -> None:  # pragma: no cover
        self._used += 1


def _create_workspace_via_api(user, payload=None):
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(WORKSPACE_CREATE_URL, payload or {"workspace_name": "QA Org"}, format="json")
    assert response.status_code == 201, response.data
    return Workspace.objects.get(id=response.data["id"])


class TestNewWorkspacesAreBoundToTheFreeTier:
    def test_create_endpoint_binds_the_free_plan(self, user_factory):
        workspace = _create_workspace_via_api(user_factory())

        assert workspace.plan is not None, "a brand-new workspace must not be plan-less (NULL == UNLIMITED)"
        assert workspace.plan.title == "Free"
        assert workspace.plan.limits[EntitlementKey.MAX_AI_RUNS_PER_MONTH.value] == FREE_AI_RUNS

    def test_onboarding_bootstrap_binds_the_free_plan(self, user_factory):
        from components.identity.application.providers.workspace_bootstrap_provider import (
            get_workspace_bootstrap_provider,
        )

        workspace = get_workspace_bootstrap_provider().create_bootstrap_workspace(user_factory())

        assert workspace is not None
        assert workspace.plan is not None, "the onboarding bootstrap path must bind a plan too"
        assert workspace.plan.title == "Free"

    def test_metered_ai_run_paywall_gates_a_new_workspace(self, user_factory):
        """The whole point of the binding: the Free cap actually blocks."""
        from components.agents.infrastructure.adapters.ai_run_quota_adapter import AiRunQuotaAdapter

        workspace = _create_workspace_via_api(user_factory())

        over = AiRunQuotaAdapter(ai_config_port=_StubAiConfigPort(999)).check_for_workspace(str(workspace.id))
        assert over.limit == FREE_AI_RUNS, "NULL plan resolves to UNLIMITED — the cap must be bound"
        assert over.allowed is False

        under = AiRunQuotaAdapter(ai_config_port=_StubAiConfigPort(1)).check_for_workspace(str(workspace.id))
        assert under.allowed is True

    def test_a_paid_plan_is_never_downgraded_by_the_binding(self, user_factory):
        """Idempotent + non-destructive: binding only fills an EMPTY plan slot."""
        from components.workspace.application.facades.workspace_facade import (
            ensure_workspace_default_plan,
        )

        workspace = _create_workspace_via_api(user_factory())
        pro = Plan.objects.get(title="Pro")
        Workspace.objects.filter(id=workspace.id).update(plan=pro)

        ensure_workspace_default_plan(workspace)

        workspace.refresh_from_db()
        assert workspace.plan_id == pro.id, "an upgraded workspace must never be reset to Free"


class TestBackfillWorkspaceDefaultPlan:
    def test_backfills_plan_less_workspaces_and_leaves_bound_ones_alone(self, user_factory):
        from django.core.management import call_command

        bound = _create_workspace_via_api(user_factory())
        pro = Plan.objects.get(title="Pro")
        Workspace.objects.filter(id=bound.id).update(plan=pro)

        stranded = _create_workspace_via_api(user_factory(), {"workspace_name": "Stranded"})
        Workspace.objects.filter(id=stranded.id).update(plan=None)

        call_command("backfill_workspace_default_plan")

        stranded.refresh_from_db()
        bound.refresh_from_db()
        assert stranded.plan is not None and stranded.plan.title == "Free"
        assert bound.plan_id == pro.id

    def test_dry_run_changes_nothing(self, user_factory):
        from django.core.management import call_command

        workspace = _create_workspace_via_api(user_factory())
        Workspace.objects.filter(id=workspace.id).update(plan=None)

        call_command("backfill_workspace_default_plan", "--dry-run")

        workspace.refresh_from_db()
        assert workspace.plan is None
