"""Unit tests for the data-driven plan entitlements model (pure domain)."""
from __future__ import annotations

from components.subscription.domain.entitlements import (
    EntitlementKey,
    EntitlementsResolver,
    PlanEntitlements,
    TIER_CATALOG,
    tier_limits,
)

PROJECTS = EntitlementKey.MAX_PROJECTS_PER_TEAM
MEMBERS = EntitlementKey.MAX_MEMBERS_PER_TEAM
TASKS = EntitlementKey.MAX_TASKS_PER_PROJECT
AI_RUNS = EntitlementKey.MAX_AI_RUNS_PER_MONTH


class TestPlanEntitlements:
    def test_limit_for_returns_cap(self):
        ent = PlanEntitlements(limits={PROJECTS.value: 3})
        assert ent.limit_for(PROJECTS) == 3
        assert ent.limit_for(PROJECTS.value) == 3  # accepts raw string too

    def test_absent_key_is_unlimited(self):
        ent = PlanEntitlements(limits={})
        assert ent.limit_for(PROJECTS) is None
        assert ent.is_unlimited(PROJECTS) is True

    def test_is_within_limit_matches_legacy_guard(self):
        # cap 3: counts 0,1,2 may create (-> 1,2,3); count 3 is blocked.
        ent = PlanEntitlements(limits={PROJECTS.value: 3})
        assert ent.is_within_limit(PROJECTS, 0) is True
        assert ent.is_within_limit(PROJECTS, 2) is True
        assert ent.is_within_limit(PROJECTS, 3) is False
        assert ent.is_within_limit(PROJECTS, 4) is False

    def test_unlimited_always_permits(self):
        ent = PlanEntitlements(limits={})
        assert ent.is_within_limit(PROJECTS, 10_000) is True

    def test_as_dict_covers_every_key(self):
        ent = PlanEntitlements(limits={PROJECTS.value: 3})
        d = ent.as_dict()
        assert set(d) == set(EntitlementKey.values())
        assert d[PROJECTS.value] == 3
        assert d[MEMBERS.value] is None  # unlimited where unset


class TestEntitlementsResolver:
    def test_plan_only(self):
        ent = EntitlementsResolver.resolve(plan_limits={PROJECTS.value: 10})
        assert ent.limit_for(PROJECTS) == 10

    def test_empty_resolves_to_all_unlimited(self):
        # Preserves legacy "no plan -> no block".
        ent = EntitlementsResolver.resolve()
        assert ent.is_unlimited(PROJECTS)
        assert ent.is_unlimited(MEMBERS)
        assert ent.is_unlimited(TASKS)

    def test_legacy_zero_normalises_to_unlimited(self):
        # The old IntegerField(default=0) sentinel meant "no limit".
        ent = EntitlementsResolver.resolve(plan_limits={PROJECTS.value: 0})
        assert ent.is_unlimited(PROJECTS)

    def test_workspace_override_widens_plan(self):
        ent = EntitlementsResolver.resolve(
            plan_limits={PROJECTS.value: 3},
            workspace_overrides={PROJECTS.value: 25},
        )
        assert ent.limit_for(PROJECTS) == 25

    def test_workspace_override_can_unlimit(self):
        ent = EntitlementsResolver.resolve(
            plan_limits={PROJECTS.value: 3},
            workspace_overrides={PROJECTS.value: None},
        )
        assert ent.is_unlimited(PROJECTS)

    def test_override_only_affects_named_keys(self):
        ent = EntitlementsResolver.resolve(
            plan_limits={PROJECTS.value: 3, MEMBERS.value: 5},
            workspace_overrides={PROJECTS.value: 25},
        )
        assert ent.limit_for(PROJECTS) == 25
        assert ent.limit_for(MEMBERS) == 5  # untouched

    def test_unknown_keys_ignored(self):
        ent = EntitlementsResolver.resolve(
            plan_limits={"max_unicorns": 99, PROJECTS.value: 3},
        )
        assert ent.limit_for(PROJECTS) == 3
        assert ent.as_dict().get("max_unicorns") is None


class TestTierCatalog:
    def test_three_marketed_tiers(self):
        assert set(TIER_CATALOG) == {"Free", "Pro", "Premium"}

    def test_free_below_pro_on_numeric_dims(self):
        free = TIER_CATALOG["Free"]
        pro = TIER_CATALOG["Pro"]
        for key in (PROJECTS.value, MEMBERS.value, TASKS.value, AI_RUNS.value):
            assert free[key] < pro[key], key

    def test_premium_is_unlimited_everywhere(self):
        # Empty map ⇒ every dimension resolves to UNLIMITED (None).
        assert TIER_CATALOG["Premium"] == {}
        ent = EntitlementsResolver.resolve(plan_limits=tier_limits("Premium"))
        for key in EntitlementKey.values():
            assert ent.is_unlimited(key), key

    def test_free_is_canonical(self):
        assert TIER_CATALOG["Free"] == {
            PROJECTS.value: 3,
            MEMBERS.value: 5,
            TASKS.value: 10,
            AI_RUNS.value: 20,
        }

    def test_free_meters_ai_runs(self):
        ent = EntitlementsResolver.resolve(plan_limits=tier_limits("Free"))
        assert ent.limit_for(AI_RUNS) == 20
        assert ent.is_within_limit(AI_RUNS, 19) is True
        assert ent.is_within_limit(AI_RUNS, 20) is False  # cap reached

    def test_tier_limits_case_insensitive(self):
        assert tier_limits("free") == TIER_CATALOG["Free"]
        assert tier_limits("PRO") == TIER_CATALOG["Pro"]
        assert tier_limits("premium") == TIER_CATALOG["Premium"]

    def test_tier_limits_unknown_is_empty(self):
        assert tier_limits("Enterprise") == {}

    def test_tier_limits_returns_copy(self):
        limits = tier_limits("Free")
        limits[PROJECTS.value] = 999
        assert TIER_CATALOG["Free"][PROJECTS.value] == 3
