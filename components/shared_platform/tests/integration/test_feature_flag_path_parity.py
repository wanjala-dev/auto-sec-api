"""Differential guard: the single-flag gate and the bulk bootstrap must agree.

The frontend bootstraps its whole flag map from ``flags_for_context``
(``/feature-flags/``, and embedded in ``/identity/me/summary/``) while every
backend gate calls ``evaluate_feature_flag``. Before ADR 0020 P0 those were two
independent implementations of the same precedence ladder — so a precedence fix
applied to one and missed on the other would silently show a feature the backend
refuses, or hide one it allows.

They now share one pure ``_resolve``. This module is what keeps that true: it
asserts the two paths return the SAME ``(enabled, source)`` for the same key
across the full rule matrix, so re-forking one path fails CI immediately.

Matrix per flag: user rule × workspace rule × global rule, each one of
{absent, on, off, on-but-expired, on-but-not-yet-started} (5³ = 125), crossed
with ``default_enabled`` ∈ {False, True} → 250 flags. Re-run with the plan tier
unlocking half of them. Plus the missing-flag case, the no-workspace context and
the anonymous context.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from components.shared_platform.application.config import tier_features
from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
    evaluate_feature_flag,
    flags_for_context,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule

pytestmark = [pytest.mark.django_db, pytest.mark.real_feature_flags]

# Rule states. "absent" means no row at that scope at all.
ABSENT, ON, OFF, EXPIRED, FUTURE = "x", "n", "f", "e", "u"
STATES = (ABSENT, ON, OFF, EXPIRED, FUTURE)


def _rule_kwargs(state: str, now):
    """Field values for a rule in ``state``, or None when no row should exist."""
    if state == ABSENT:
        return None
    if state == ON:
        return {"enabled": True}
    if state == OFF:
        return {"enabled": False}
    if state == EXPIRED:
        # Enabled, but its window closed an hour ago — must be ignored.
        return {"enabled": True, "starts_at": now - timedelta(days=1), "ends_at": now - timedelta(hours=1)}
    if state == FUTURE:
        # Enabled, but scheduled to start in an hour — must be ignored.
        return {"enabled": True, "starts_at": now + timedelta(hours=1)}
    raise AssertionError(f"unknown state {state!r}")


@pytest.fixture
def flag_matrix(user_factory, workspace_factory):
    """Create one FeatureFlag per (user, workspace, global, default) combination."""
    user = user_factory()
    workspace = workspace_factory(owner=user)
    now = timezone.now()

    flags = []
    keys = []
    for user_state in STATES:
        for workspace_state in STATES:
            for global_state in STATES:
                for default_enabled in (False, True):
                    key = f"diff.u{user_state}_w{workspace_state}_g{global_state}_d{int(default_enabled)}"
                    keys.append((key, user_state, workspace_state, global_state))
                    flags.append(FeatureFlag(key=key, default_enabled=default_enabled))

    FeatureFlag.objects.bulk_create(flags)
    by_key = {flag.key: flag for flag in FeatureFlag.objects.filter(key__startswith="diff.")}

    rules = []
    for key, user_state, workspace_state, global_state in keys:
        flag = by_key[key]
        for scope, state, target in (
            (FeatureFlagRule.Scope.USER, user_state, {"user": user}),
            (FeatureFlagRule.Scope.WORKSPACE, workspace_state, {"workspace": workspace}),
            (FeatureFlagRule.Scope.GLOBAL, global_state, {}),
        ):
            fields = _rule_kwargs(state, now)
            if fields is None:
                continue
            rules.append(FeatureFlagRule(flag=flag, scope=scope, **target, **fields))

    FeatureFlagRule.objects.bulk_create(rules)
    # bulk_create skips post_save, so the signal bridge never fired — invalidate
    # by hand exactly as production does on any flag write.
    bump_feature_flags_version()

    return {"user": user, "workspace": workspace, "keys": [key for key, *_ in keys]}


def _assert_paths_agree(keys, *, user, workspace_id, label):
    """Both paths, same context, same answer — value AND source attribution."""
    bulk = flags_for_context(user=user, workspace_id=workspace_id, include_sources=True)

    mismatches = []
    for key in keys:
        single = evaluate_feature_flag(key, user=user, workspace_id=workspace_id)
        row = bulk.get(key)
        assert row is not None, f"[{label}] {key} missing from the bulk map"
        if (single.enabled, single.source) != (row["enabled"], row["source"]):
            mismatches.append(
                f"  {key}: evaluate_feature_flag={single.enabled}/{single.source} "
                f"!= flags_for_context={row['enabled']}/{row['source']}"
            )

    assert not mismatches, (
        f"[{label}] the single-flag gate and the bulk bootstrap disagree on "
        f"{len(mismatches)}/{len(keys)} flags:\n" + "\n".join(mismatches[:25])
    )


def test_paths_agree_across_the_full_rule_matrix(flag_matrix):
    keys = flag_matrix["keys"]
    assert len(keys) == 250, "matrix size changed — update the assertion deliberately"

    _assert_paths_agree(
        keys,
        user=flag_matrix["user"],
        workspace_id=str(flag_matrix["workspace"].id),
        label="user+workspace",
    )


def test_paths_agree_without_a_workspace(flag_matrix):
    """No workspace => workspace rules and the plan tier are both out of play."""
    _assert_paths_agree(flag_matrix["keys"], user=flag_matrix["user"], workspace_id=None, label="user only")


def test_paths_agree_for_an_anonymous_context(flag_matrix):
    """No user => user rules are out of play; workspace/global/default still rule."""
    _assert_paths_agree(
        flag_matrix["keys"],
        user=None,
        workspace_id=str(flag_matrix["workspace"].id),
        label="workspace only",
    )


def test_paths_agree_when_the_plan_tier_unlocks(flag_matrix, monkeypatch):
    """The plan-tier layer sits between workspace and global, and only unlocks.

    Re-runs the whole matrix with the workspace's tier unlocking every other
    flag, so tier-vs-rule precedence is exercised against all 5³ rule shapes.
    """
    workspace = flag_matrix["workspace"]
    tier_title = workspace.plan.title
    unlocked = frozenset(flag_matrix["keys"][::2])

    monkeypatch.setitem(tier_features.TIER_FEATURE_MAP, tier_title, unlocked)
    # TIER_FEATURE_MAP is a code constant; changing it does not write a row, so
    # nothing bumps the cache version for us.
    bump_feature_flags_version()

    _assert_paths_agree(
        flag_matrix["keys"],
        user=flag_matrix["user"],
        workspace_id=str(workspace.id),
        label="plan tier unlocks half",
    )

    # Sanity: the tier layer really did fire on both paths (otherwise agreement
    # would be vacuous — TIER_FEATURE_MAP ships empty today).
    bulk = flags_for_context(user=flag_matrix["user"], workspace_id=str(workspace.id), include_sources=True)
    tier_sourced = {key for key in flag_matrix["keys"] if bulk[key]["source"] == "plan_tier"}
    assert tier_sourced, "no flag resolved via plan_tier — the tier fixture is inert"
    assert tier_sourced <= unlocked, "plan_tier fired for a flag the tier does not unlock"
    sample = sorted(tier_sourced)[0]
    assert evaluate_feature_flag(sample, user=flag_matrix["user"], workspace_id=str(workspace.id)).source == "plan_tier"


def test_a_missing_flag_is_off_on_both_paths(flag_matrix):
    """The single path reports `missing_flag`; the bulk map simply omits the key.
    Different shapes, same meaning — and the frontend must not see it as ON."""
    workspace_id = str(flag_matrix["workspace"].id)

    single = evaluate_feature_flag("diff.never_created", user=flag_matrix["user"], workspace_id=workspace_id)
    assert (single.enabled, single.source) == (False, "missing_flag")

    bulk = flags_for_context(user=flag_matrix["user"], workspace_id=workspace_id, include_sources=True)
    assert "diff.never_created" not in bulk


def test_bulk_path_query_count_is_constant_in_flag_count(user_factory, workspace_factory):
    """The bulk bootstrap must stay one-query-per-concern as the flag table grows.

    Counts are compared against each other, never asserted as an absolute.
    """
    user = user_factory()
    workspace = workspace_factory(owner=user)
    workspace_id = str(workspace.id)

    def _seed(prefix: str, count: int):
        flags = FeatureFlag.objects.bulk_create(
            [FeatureFlag(key=f"qc.{prefix}.{index}", default_enabled=index % 2 == 0) for index in range(count)]
        )
        stored = list(FeatureFlag.objects.filter(key__startswith=f"qc.{prefix}."))
        FeatureFlagRule.objects.bulk_create(
            [
                FeatureFlagRule(flag=flag, scope=FeatureFlagRule.Scope.WORKSPACE, workspace=workspace, enabled=True)
                for flag in stored
            ]
            + [
                FeatureFlagRule(flag=flag, scope=FeatureFlagRule.Scope.USER, user=user, enabled=False)
                for flag in stored
            ]
        )
        bump_feature_flags_version()
        return flags

    def _count() -> int:
        bump_feature_flags_version()  # force a cache miss so we measure the real read
        with CaptureQueriesContext(connection) as ctx:
            flags_for_context(user=user, workspace_id=workspace_id)
        return len(ctx.captured_queries)

    _seed("small", 5)
    small = _count()

    _seed("large", 45)
    large = _count()

    assert small == large, (
        f"flags_for_context went from {small} to {large} queries when the flag count grew "
        f"10× — an N+1 crept into the bulk bootstrap"
    )
