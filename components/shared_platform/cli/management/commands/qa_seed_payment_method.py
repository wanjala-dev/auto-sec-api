"""Seed a minimal active WorkspacePaymentMethod for a QA E2E workspace.

Several GTM surfaces gate on the workspace having a payment method before
they'll provision priced artifacts — donation-form tiers
(``donation_form_tier_repository.create_tier`` → "Connect a payment method
… before adding tiers"), sponsorship plans, etc. A fresh local org has no
Stripe Connect account, so those loops can't be exercised end to end
without one.

Tier / plan creation itself is a LOCAL DB operation (it writes a
``PaymentPlan`` row against the method) — no live Stripe call — so a
minimal seeded method row unblocks the full builder → tiers → publish →
public-serve loop for the QA suite. The actual CHARGE still needs real
Stripe and stays in the demo ``@money`` specs.

Guard rails (same as the other qa_* commands): DEBUG-only (or
``QA_E2E_ALLOW=1``) AND the target workspace's owner must be on the
dedicated QA email domain — so this can never seed a real customer
workspace with a bogus method.

Usage:
    python manage.py qa_seed_payment_method --workspace-id <uuid>
"""

from __future__ import annotations

import json

from django.core.management import BaseCommand, CommandError

from components.shared_platform.cli.management.commands.qa_email_token import QA_DOMAIN, qa_commands_allowed


class Command(BaseCommand):
    help = "Seed an active WorkspacePaymentMethod for a *@qa.octopi.dev-owned workspace (E2E glue)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", required=True, help="Target workspace UUID.")
        parser.add_argument("--domain", default=QA_DOMAIN, help=f"Allowed owner domain (default: {QA_DOMAIN}).")
        parser.add_argument("--currency", default="usd", help="Settlement currency (default: usd).")

    def handle(self, *args, **options):
        if not qa_commands_allowed():
            raise CommandError("qa_seed_payment_method is disabled outside DEBUG (set QA_E2E_ALLOW=1 to override).")

        from infrastructure.persistence.workspaces.models import Workspace
        from infrastructure.persistence.workspaces.payments.models import (
            PaymentProvider,
            WorkspacePaymentMethod,
        )

        workspace_id = options["workspace_id"]
        domain = options["domain"].strip().lower()

        workspace = Workspace.objects.filter(id=workspace_id).select_related("workspace_owner").first()
        if workspace is None:
            raise CommandError(f"no workspace {workspace_id}")

        owner_email = (getattr(workspace.workspace_owner, "email", "") or "").lower()
        if not owner_email.endswith(f"@{domain}"):
            raise CommandError(
                f"refusing: workspace {workspace_id} owner ({owner_email or 'none'}) is not on @{domain}"
            )

        provider = PaymentProvider.objects.first()
        if provider is None:
            raise CommandError("no PaymentProvider seeded — run seed_payment_providers first")

        method, created = WorkspacePaymentMethod.objects.get_or_create(
            workspace_id=workspace_id,
            provider=provider,
            defaults={
                "display_name": "QA Local Method",
                "status": "active",
                "is_primary": True,
                "provider_account_id": "acct_qa_local",
                "settlement_currency": options["currency"],
            },
        )
        if not created and method.status != "active":
            method.status = "active"
            method.save(update_fields=["status"])

        self.stdout.write(
            json.dumps(
                {
                    "workspace_id": str(workspace_id),
                    "method_id": str(method.id),
                    "status": method.status,
                    "created": created,
                }
            )
        )
