"""Unit tests for the canonical plan catalogue (pure — no DB)."""
from __future__ import annotations

from components.subscription.application.config.plan_catalog import (
    TIER_ORDER,
    canonical_plan_specs,
)
from components.subscription.domain.entitlements import EntitlementKey, TIER_CATALOG


def test_specs_cover_exactly_the_three_marketed_tiers():
    titles = [s["title"] for s in canonical_plan_specs()]
    assert titles == ["Free", "Pro", "Premium"]
    assert TIER_ORDER == ("Free", "Pro", "Premium")
    assert set(titles) == set(TIER_CATALOG)


def test_limits_come_from_tier_catalog_not_hardcoded():
    by_title = {s["title"]: s for s in canonical_plan_specs()}
    for title in ("Free", "Pro", "Premium"):
        assert by_title[title]["limits"] == TIER_CATALOG[title]


def test_free_is_the_only_default_and_is_free():
    specs = canonical_plan_specs()
    defaults = [s for s in specs if s["is_default"]]
    assert [s["title"] for s in defaults] == ["Free"]
    free = next(s for s in specs if s["title"] == "Free")
    assert free["price"] == 0


def test_prices_ascend_free_pro_premium():
    by_title = {s["title"]: s for s in canonical_plan_specs()}
    assert by_title["Free"]["price"] < by_title["Pro"]["price"] < by_title["Premium"]["price"]


def test_every_spec_is_materialisable():
    # Every key the Plan model needs is present.
    required = {"title", "price", "is_default", "billing_interval", "interval_count", "currency", "limits"}
    for spec in canonical_plan_specs():
        assert required <= set(spec)


def test_free_meters_ai_runs():
    free = next(s for s in canonical_plan_specs() if s["title"] == "Free")
    assert free["limits"][EntitlementKey.MAX_AI_RUNS_PER_MONTH.value] == 20
