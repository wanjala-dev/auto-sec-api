"""P4 — a tier change invalidates the feature-flag cache.

The plan-tier layer of feature-flag resolution (and the metered-AI
entitlement) keys off ``Workspace.plan``. When billing applies a new tier,
the global feature-flag cache version MUST bump so the new tier's feature
set unlocks/re-locks on the next evaluation instead of waiting out the 300s
TTL. These tests exercise the real write seams in
``TeamPlanBillingRepository`` and assert the observable cache-version change
(no mocks).
"""
from __future__ import annotations

import pytest

from components.payments.infrastructure.repositories.team_plan_billing_repository import (
    TeamPlanBillingRepository,
)
from components.shared_platform.infrastructure.services.feature_flags import (
    _get_or_init_version,
)


def _plan(title: str, *, price: int = 0, is_default: bool = False):
    from infrastructure.persistence.subscription.models import Plan

    return Plan.objects.create(title=title, price=price, is_default=is_default, limits={})


@pytest.mark.django_db
class TestPlanChangeBumpsFeatureFlagCache:
    def test_applying_a_new_tier_bumps_the_cache_and_writes_the_plan(
        self, user_factory, workspace_factory
    ):
        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Free")
        ws.save(update_fields=["plan"])
        pro = _plan("Pro", price=2500)

        before = _get_or_init_version()
        TeamPlanBillingRepository._sync_workspace_plan_from_subscription(ws, pro, None)
        after = _get_or_init_version()

        ws.refresh_from_db()
        assert ws.plan_id == pro.id
        assert after > before  # cache invalidated → Pro features unlock now

    def test_status_only_sync_without_plan_change_does_not_bump(
        self, user_factory, workspace_factory
    ):
        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Pro", price=2500)
        ws.save(update_fields=["plan"])

        before = _get_or_init_version()
        # plan=None → status/period sync only; the tier did not change.
        TeamPlanBillingRepository._sync_workspace_plan_from_subscription(ws, None, None)
        after = _get_or_init_version()

        assert after == before  # no needless global cache flush

    def test_subscription_deleted_falls_back_to_free_and_bumps(
        self, user_factory, workspace_factory
    ):
        ws = workspace_factory(owner=user_factory())
        ws.plan = _plan("Pro", price=2500)
        ws.save(update_fields=["plan"])
        free = _plan("Free", is_default=True)

        before = _get_or_init_version()
        TeamPlanBillingRepository().sync_deleted_subscription(workspace=ws)
        after = _get_or_init_version()

        ws.refresh_from_db()
        assert ws.plan_id == free.id  # re-locked to Free
        assert after > before
