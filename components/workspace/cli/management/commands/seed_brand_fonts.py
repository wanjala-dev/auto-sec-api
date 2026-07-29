"""Seed the curated brand-font catalog.

Usage:

    python manage.py seed_brand_fonts

Idempotent — upserts on ``key`` so re-running updates stacks/labels in place
and never duplicates. Entries removed from the seed list are deactivated (not
deleted) so workspaces referencing them keep resolving until re-pointed.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from components.workspace.infrastructure.font_catalog_seed import BRAND_FONT_CATALOG


class Command(BaseCommand):
    help = "Seed/refresh the curated BrandFontOption catalog (idempotent)."

    def handle(self, *args, **options):
        from infrastructure.persistence.workspaces.theming.models import BrandFontOption

        seeded_keys = []
        created_count = 0
        for entry in BRAND_FONT_CATALOG:
            _, created = BrandFontOption.objects.update_or_create(
                key=entry["key"],
                defaults={
                    "label": entry["label"],
                    "category": entry["category"],
                    "css_stack": entry["css_stack"],
                    "google_family": entry["google_family"],
                    "sort_order": entry["sort_order"],
                    "active": True,
                },
            )
            seeded_keys.append(entry["key"])
            if created:
                created_count += 1

        deactivated = BrandFontOption.objects.exclude(key__in=seeded_keys).filter(active=True).update(active=False)

        self.stdout.write(
            self.style.SUCCESS(
                f"Brand fonts seeded: {len(seeded_keys)} entries ({created_count} created, {deactivated} deactivated)."
            )
        )
