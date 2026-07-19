"""Seed the default payment provider catalog.

Ensures at least the Stripe provider row exists so that workspace admins
can configure payment methods immediately after deployment.

Idempotent — safe to run on every boot.

Usage:
    python manage.py seed_payment_providers
"""

from __future__ import annotations

from django.core.management import BaseCommand


PROVIDERS = [
    {
        "slug": "stripe",
        "defaults": {
            "display_name": "Stripe",
            "provider_type": "api",
            "capabilities": [
                "donations",
                "shop",
                "campaign",
                "event",
                "recipient_sponsorship",
                "workspace_support",
                "team_plan",
            ],
            "config_template": {},
            "oauth_settings": {},
            "is_active": True,
        },
    },
]


class Command(BaseCommand):
    help = "Seed default payment providers (Stripe, etc.)."

    def handle(self, *args, **options):
        from infrastructure.persistence.workspaces.payments.models import (
            PaymentProvider,
        )

        for spec in PROVIDERS:
            _, created = PaymentProvider.objects.get_or_create(
                slug=spec["slug"],
                defaults=spec["defaults"],
            )
            verb = "Created" if created else "Already exists"
            self.stdout.write(f"  {verb}: {spec['slug']}")

        self.stdout.write(self.style.SUCCESS("Payment providers seeded."))
