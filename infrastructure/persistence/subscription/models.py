from django.db import models

# Subscription tier (the platform's own SaaS feature tier — Free / Pro / Premium).
#
# This model is the canonical home for subscription plans. It was relocated here
# from the ``team`` app (its original, legacy placement) so the bounded context
# that owns subscription logic also owns the persistence — see
# docs/plans/PREMIUM_FEATURE_TIERS_PLAN.md.
#
# The physical table is preserved as ``team_plan`` (a pure state move via
# SeparateDatabaseAndState — no data movement). Renaming the table is an
# optional cosmetic follow-up, deliberately deferred to avoid touching live
# billing data.
#
# Tier definitions (titles, numeric limits, AI cap) are the single source of
# truth in ``components.subscription.domain.entitlements`` (TIER_CATALOG); the
# canonical seeder reads it. Nothing hard-codes the numbers anymore.


class Plan(models.Model):
    title = models.CharField(max_length=255)
    # Numeric entitlements: {EntitlementKey: int}. A missing key (or None)
    # means unlimited. Adding a new quota dimension is a new EntitlementKey +
    # seed data — never a schema migration. Reads go through
    # ``components.subscription.domain.entitlements.EntitlementsResolver``.
    # Boolean tier features ride the FeatureFlag/FeatureFlagRule system, not
    # this map. (The legacy max_*_per_* columns were dropped in team migration
    # 0010 — see ADR 0005.)
    limits = models.JSONField(default=dict, blank=True)
    price = models.IntegerField(default=0)
    is_default = models.BooleanField(default=False)
    billing_interval = models.CharField(max_length=10, default="month")
    interval_count = models.PositiveIntegerField(default=1)
    currency = models.CharField(max_length=10, default="usd")
    stripe_product_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_price_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        # Preserve the original physical table — this was a pure state move
        # (SeparateDatabaseAndState), so the data never moved.
        db_table = "team_plan"

    def __str__(self):
        return self.title
