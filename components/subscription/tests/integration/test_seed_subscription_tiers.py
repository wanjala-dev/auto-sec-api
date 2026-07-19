"""Integration test for the canonical subscription-tier seeder."""
from __future__ import annotations

import pytest
from django.core.management import call_command

from infrastructure.persistence.subscription.models import Plan
from components.subscription.domain.entitlements import TIER_CATALOG


@pytest.mark.django_db
def test_seed_creates_the_three_canonical_tiers():
    Plan.objects.all().delete()
    call_command("seed_subscription_tiers")

    titles = set(Plan.objects.values_list("title", flat=True))
    assert titles == {"Free", "Pro", "Premium"}

    for title in titles:
        plan = Plan.objects.get(title=title)
        assert plan.limits == TIER_CATALOG[title]

    # Exactly one default, and it's Free.
    defaults = list(Plan.objects.filter(is_default=True).values_list("title", flat=True))
    assert defaults == ["Free"]


@pytest.mark.django_db
def test_seed_is_idempotent_and_reconciles_drift():
    Plan.objects.all().delete()
    # A drifted Pro row (wrong limits + price + stray default flag).
    Plan.objects.create(title="Pro", limits={"max_projects_per_team": 1}, price=999, is_default=True)

    call_command("seed_subscription_tiers")
    call_command("seed_subscription_tiers")  # second run must be a no-op-safe

    assert Plan.objects.filter(title="Pro").count() == 1
    pro = Plan.objects.get(title="Pro")
    assert pro.limits == TIER_CATALOG["Pro"]
    assert pro.price == 25
    assert pro.is_default is False
    assert list(Plan.objects.filter(is_default=True).values_list("title", flat=True)) == ["Free"]
