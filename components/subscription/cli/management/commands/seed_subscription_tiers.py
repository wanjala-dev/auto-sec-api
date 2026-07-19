"""Seed the canonical subscription tiers — the ONE seeder for Plan rows.

Idempotently upserts Free / Pro / Premium from
``components.subscription.application.config.plan_catalog.canonical_plan_specs`` (the
single source of truth). Every other bootstrap path delegates here via
``call_command('seed_subscription_tiers')`` instead of hard-coding tier
definitions — see docs/plans/PREMIUM_FEATURE_TIERS_PLAN.md.

Safe to re-run. Keyed by ``title``; existing rows are updated to the canonical
limits/price (so a deploy reconciles drift). Guarantees exactly one default
plan (Free).

    docker exec compose-web-1 python manage.py seed_subscription_tiers
"""
from __future__ import annotations

from django.core.management import BaseCommand
from django.db import transaction

from components.subscription.application.config.plan_catalog import canonical_plan_specs


class Command(BaseCommand):
    help = "Idempotently seed the canonical subscription tiers (Free/Pro/Premium)."

    def handle(self, *args, **options):
        from infrastructure.persistence.subscription.models import Plan

        created_n = updated_n = 0
        with transaction.atomic():
            for spec in canonical_plan_specs():
                title = spec["title"]
                defaults = {k: v for k, v in spec.items() if k != "title"}
                plan, created = Plan.objects.get_or_create(title=title, defaults=defaults)
                if created:
                    created_n += 1
                    self.stdout.write(self.style.SUCCESS(f"Created plan: {title}"))
                    continue
                changed = [
                    key for key, value in defaults.items() if getattr(plan, key) != value
                ]
                if changed:
                    for key in changed:
                        setattr(plan, key, defaults[key])
                    plan.save(update_fields=changed)
                    updated_n += 1
                    self.stdout.write(self.style.SUCCESS(f"Updated plan {title}: {changed}"))

            # Exactly one default tier (Free). Defensive against any stray
            # is_default left on a non-Free row by an older seeder.
            Plan.objects.exclude(title="Free").filter(is_default=True).update(is_default=False)

        self.stdout.write(
            self.style.NOTICE(f"Subscription tiers ready (created={created_n}, updated={updated_n}).")
        )
