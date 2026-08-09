"""Unit coverage for the shared precedence ladder (`_resolve`), ADR 0020 P0.

`_resolve` is the ONE implementation of

    user rule -> workspace rule -> plan tier -> global rule -> default

that both `evaluate_feature_flag` (single-flag gate) and `flags_for_context`
(bulk frontend bootstrap) derive their answer from.

**This module deliberately carries no `django_db` marker.** That is the
mechanical proof of the purity requirement: if `_resolve` ever reaches for the
ORM, the cache or the request, pytest-django fails the test with "Database
access not allowed" rather than silently passing. Plain dicts and a plain
frozenset satisfy its two duck-typed inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from components.shared_platform.infrastructure.services.feature_flags import _resolve
from infrastructure.persistence.core.models import FeatureFlagRule

pytestmark = [pytest.mark.unit]

NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)
USER = FeatureFlagRule.Scope.USER
WORKSPACE = FeatureFlagRule.Scope.WORKSPACE
GLOBAL = FeatureFlagRule.Scope.GLOBAL


@dataclass(frozen=True)
class _Rule:
    """Stand-in for a FeatureFlagRule row — same duck type, no ORM."""

    enabled: bool
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    def is_active_now(self, now=None) -> bool:
        now = now or NOW
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True


def _resolved(rules=None, *, tier=frozenset(), default_enabled=False, key="demo.flag"):
    return _resolve(
        flag_key=key,
        default_enabled=default_enabled,
        rules_by_scope=rules or {},
        tier_unlocked=tier,
        now=NOW,
    )


def test_default_is_the_floor():
    assert _resolved(default_enabled=False) == _resolved(default_enabled=False)
    assert (_resolved(default_enabled=False).enabled, _resolved(default_enabled=False).source) == (False, "default")
    assert (_resolved(default_enabled=True).enabled, _resolved(default_enabled=True).source) == (True, "default")


def test_global_rule_beats_default_in_both_directions():
    on = _resolved({GLOBAL: _Rule(enabled=True)}, default_enabled=False)
    assert (on.enabled, on.source) == (True, "global_rule")

    off = _resolved({GLOBAL: _Rule(enabled=False)}, default_enabled=True)
    assert (off.enabled, off.source) == (False, "global_rule")


def test_plan_tier_beats_global_and_only_ever_unlocks():
    # A tier unlock overrides a global disable...
    unlocked = _resolved({GLOBAL: _Rule(enabled=False)}, tier=frozenset({"demo.flag"}))
    assert (unlocked.enabled, unlocked.source) == (True, "plan_tier")

    # ...and a flag the tier does not carry falls straight through.
    passthrough = _resolved({GLOBAL: _Rule(enabled=True)}, tier=frozenset({"demo.other"}))
    assert (passthrough.enabled, passthrough.source) == (True, "global_rule")


def test_workspace_rule_beats_plan_tier_and_global():
    result = _resolved(
        {WORKSPACE: _Rule(enabled=False), GLOBAL: _Rule(enabled=True)},
        tier=frozenset({"demo.flag"}),
    )
    assert (result.enabled, result.source) == (False, "workspace_rule")


def test_user_rule_beats_everything():
    """User-beats-workspace is load-bearing (feature.support_impersonation,
    PROD_ALLOWLISTED_USER_FLAGS) and ADR 0020 D0 forbids reordering it."""
    result = _resolved(
        {USER: _Rule(enabled=True), WORKSPACE: _Rule(enabled=False), GLOBAL: _Rule(enabled=False)},
        tier=frozenset(),
        default_enabled=False,
    )
    assert (result.enabled, result.source) == (True, "user_rule")

    # ...and a user rule can also disable what everything below turns on.
    result = _resolved(
        {USER: _Rule(enabled=False), WORKSPACE: _Rule(enabled=True), GLOBAL: _Rule(enabled=True)},
        tier=frozenset({"demo.flag"}),
        default_enabled=True,
    )
    assert (result.enabled, result.source) == (False, "user_rule")


@pytest.mark.parametrize(
    "window",
    [
        pytest.param({"ends_at": NOW - timedelta(hours=1)}, id="expired"),
        pytest.param({"starts_at": NOW + timedelta(hours=1)}, id="not_yet_started"),
    ],
)
@pytest.mark.parametrize("scope", [USER, WORKSPACE, GLOBAL])
def test_out_of_window_rules_are_invisible_at_every_scope(scope, window):
    """An inactive rule must not merely evaluate to its own value — it must be
    skipped so the NEXT layer decides."""
    result = _resolved({scope: _Rule(enabled=True, **window)}, default_enabled=False)
    assert (result.enabled, result.source) == (False, "default")


def test_an_inactive_higher_rule_yields_to_an_active_lower_one():
    result = _resolved(
        {
            USER: _Rule(enabled=False, ends_at=NOW - timedelta(hours=1)),
            WORKSPACE: _Rule(enabled=True),
        },
        default_enabled=False,
    )
    assert (result.enabled, result.source) == (True, "workspace_rule")
