"""Scanner capabilities default ON — backfill for EXISTING databases.

The four scanner capability flags — ``feature.cloud_posture``,
``feature.container_security``, ``feature.code_security``,
``feature.vercel_posture`` — ship in Free
(docs/product/PRICING_PACKAGING_RECOMMENDATION_2026-08-08.md), so their job is
kill-switch, not entitlement gate. ``seed_feature_flags`` now creates them with
``default_enabled=True``, but the seed only ``get_or_create``s — it cannot
retro-fix rows that already exist. This data migration:

1. Flips ``FeatureFlag.default_enabled`` to ``True`` for exactly these keys.
2. Deletes the SEED-CREATED global disable rules for these keys (matched on the
   seed's exact note) — the artifact of the old "off in prod until GA" policy.

It deliberately touches NOTHING else: operator-created GLOBAL rules and every
WORKSPACE/USER rule survive, so an explicit disable still wins via the resolver
ladder (user → workspace → tier → global → default). Idempotent.

No cache-version bump here (migrations stay pure ORM): every deploy path runs
``seed_feature_flags`` on api startup right after migrate, and the seed bumps
the feature-flag cache version.
"""

from django.db import migrations

SCANNER_CAPABILITY_FLAGS = (
    "feature.cloud_posture",
    "feature.container_security",
    "feature.code_security",
    "feature.vercel_posture",
)

# Must match seed_feature_flags.PROD_DISABLE_NOTE — the marker distinguishing
# seed-created disable rules from operator-created ones (never touched).
SEED_PROD_DISABLE_NOTE = "Disabled in production by seed_feature_flags."


def scanner_capabilities_default_on(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    FeatureFlag = apps.get_model("core", "FeatureFlag")
    FeatureFlagRule = apps.get_model("core", "FeatureFlagRule")

    FeatureFlag.objects.using(db_alias).filter(key__in=SCANNER_CAPABILITY_FLAGS).update(default_enabled=True)
    FeatureFlagRule.objects.using(db_alias).filter(
        flag__key__in=SCANNER_CAPABILITY_FLAGS,
        scope="global",
        note=SEED_PROD_DISABLE_NOTE,
    ).delete()


def scanner_capabilities_default_off(apps, schema_editor):
    """Reverse: restore default-off. Deleted seed rules are not resurrected —
    re-running seed_feature_flags in prod recreates them for keys still in
    PROD_DISABLED_FLAGS."""
    db_alias = schema_editor.connection.alias
    FeatureFlag = apps.get_model("core", "FeatureFlag")
    FeatureFlag.objects.using(db_alias).filter(key__in=SCANNER_CAPABILITY_FLAGS).update(default_enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_background_job"),
    ]

    operations = [
        migrations.RunPython(scanner_capabilities_default_on, scanner_capabilities_default_off),
    ]
