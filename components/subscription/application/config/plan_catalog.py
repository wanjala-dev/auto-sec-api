"""The single canonical definition of the platform's subscription tiers.

This is THE one place that says what Plan rows exist (Free / Pro / Premium),
combining:
  - numeric limits from ``TIER_CATALOG`` (the domain source of truth), and
  - billing attributes (price, default flag, interval, currency).

Every seeder reads ``canonical_plan_specs()`` and upserts from it — nothing
hard-codes tier titles or limit numbers anymore. The canonical seeder is the
``seed_subscription_tiers`` management command; all other bootstrap paths
delegate to it. See docs/plans/PREMIUM_FEATURE_TIERS_PLAN.md.

Layering: application layer — composes domain data (TIER_CATALOG) with billing
attributes. No framework / ORM imports here (pure data); the ORM upsert lives
in the management command.
"""
from __future__ import annotations

from components.subscription.domain.entitlements import TIER_CATALOG, tier_limits

# Billing attributes per marketed tier. LIMITS are NOT here — they are the
# domain's job (TIER_CATALOG). Prices are PLACEHOLDERS pending final pricing
# (see PREMIUM_FEATURE_TIERS_PLAN.md §8): Pro ~$25/mo, Premium ~$79/mo.
_TIER_BILLING: dict[str, dict[str, object]] = {
    "Free": {"price": 0, "is_default": True},
    "Pro": {"price": 25, "is_default": False},
    "Premium": {"price": 79, "is_default": False},
}

# Marketed order (ascending). Mirrors TIER_CATALOG; kept explicit so callers
# get a stable order without relying on dict insertion order of two sources.
TIER_ORDER: tuple[str, ...] = ("Free", "Pro", "Premium")


def canonical_plan_specs() -> list[dict]:
    """Return the full provisioning spec for every subscription tier.

    Each spec is a dict ready to materialise a ``subscription.Plan`` row:
    ``{title, price, is_default, billing_interval, interval_count, currency,
    limits}``. Limits resolve from ``TIER_CATALOG`` via ``tier_limits`` — the
    single source of truth for the numbers.
    """
    specs: list[dict] = []
    for title in TIER_ORDER:
        billing = _TIER_BILLING[title]
        specs.append(
            {
                "title": title,
                "price": billing["price"],
                "is_default": billing["is_default"],
                "billing_interval": "month",
                "interval_count": 1,
                "currency": "usd",
                "limits": tier_limits(title),
            }
        )
    return specs


# Defensive: keep the billing map and the domain catalogue in lock-step. A tier
# defined in one but not the other is a bug (a Plan with no limits, or limits
# with no price). Surfaces at import time in dev/CI rather than at seed time.
assert set(_TIER_BILLING) == set(TIER_CATALOG), (
    "plan_catalog._TIER_BILLING and entitlements.TIER_CATALOG must define the "
    f"same tiers; got {set(_TIER_BILLING)} vs {set(TIER_CATALOG)}"
)
