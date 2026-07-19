"""Subscription tier → feature-flag unlock map.

The product decision of *which feature flags each paid tier unlocks*. The
feature-flag resolver (``feature_flags.evaluate_feature_flag``) consults this as
the **plan-tier layer** in its resolution order:

    user rule → workspace rule → PLAN TIER → global → default

A paid tier turns its feature set ON even when those flags are globally-off in
prod (mirroring the existing "workspace rule wins over global disable" pattern),
while still letting an explicit user/workspace rule override (those are checked
first). Free unlocks nothing; the org sees the gated features only after
upgrading. See docs/plans/PREMIUM_FEATURE_TIERS_PLAN.md §2/§4.

Co-located with the resolver (rather than in the subscription context) so the
hot resolution path needs no cross-context import — the tier titles are plain
strings and the flag keys are the feature-flag system's own.

NOTE: some of these flags are minted in P2 (budget_ai, ai_reports, ai_writing,
time_tracking, grants_advanced). Listing them here now is harmless — the
resolver only acts on flags that actually exist (a missing flag resolves to
``missing_flag`` before the plan-tier layer is reached), so the mapping is inert
for a flag until its FeatureFlag row exists.
"""

from __future__ import annotations

# Feature sets per paid tier. Populate these with product feature-flag keys as
# paid tiers gain gated features. The resolver only acts on flags that actually
# exist (a missing flag resolves to ``missing_flag`` before the plan-tier layer
# is reached), so an empty map is inert and safe.
_PRO_FEATURES: frozenset[str] = frozenset()

# Premium inherits Pro and can add Premium-only feature keys.
_PREMIUM_FEATURES: frozenset[str] = _PRO_FEATURES | frozenset()

TIER_FEATURE_MAP: dict[str, frozenset[str]] = {
    "Free": frozenset(),
    "Pro": _PRO_FEATURES,
    "Premium": _PREMIUM_FEATURES,
}


def features_for_tier(tier_title: str | None) -> frozenset[str]:
    """Return the set of feature-flag keys a tier unlocks (empty if unknown).

    Case-insensitive on the tier title. An unknown/None tier (e.g. a workspace
    with no plan) unlocks nothing — same as Free.
    """
    if not tier_title:
        return frozenset()
    return TIER_FEATURE_MAP.get(tier_title.strip().title(), frozenset())
