"""Bind every plan-less workspace to the default (Free) subscription tier.

New workspaces are bound at creation (``ensure_workspace_default_plan``). This
repairs the rows created BEFORE that binding existed: they carry
``Workspace.plan = NULL``, which ``EntitlementsResolver`` reads as UNLIMITED —
so those workspaces are silently on a tier more generous than Pro and no paid
entitlement (today: the metered monthly AI-run allowance) can ever fire for
them. Every workspace on the 2026-08-18 QA sweep was in that state.

Idempotent and non-destructive: it only fills an EMPTY plan slot, so a paying
workspace is never touched. Safe to re-run, and safe to run on every deploy.

Dedicated tenants: management commands bind the POOLED tenant, so this repairs
the shared database. Run it once per dedicated tenant alias too — those rows
live in that tenant's own database.

Lives under ``cli/`` (the context's installed primary adapter) rather than
``infrastructure/management/``, because only ``components.workspace.cli`` is in
INSTALLED_APPS — a command under the infrastructure tree is never discovered.

Usage:
    python manage.py backfill_workspace_default_plan
    python manage.py backfill_workspace_default_plan --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from components.workspace.application.facades.workspace_facade import (
    ensure_canonical_subscription_tiers,
    ensure_workspace_default_plan,
)
from infrastructure.persistence.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Bind every workspace with no subscription plan to the default (Free) tier."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the workspaces that would be bound without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run")

        # ``all_objects()`` — inactive workspaces are just as unlimited as
        # active ones, and they become active later.
        stranded = list(Workspace.objects.all_objects().filter(plan__isnull=True).order_by("created_at"))

        if not stranded:
            self.stdout.write(self.style.NOTICE("No plan-less workspaces — nothing to backfill."))
            return

        if dry_run:
            for workspace in stranded:
                self.stdout.write(f"[dry-run] would bind: {workspace.id} ({workspace.workspace_name})")
            self.stdout.write(self.style.NOTICE(f"[dry-run] {len(stranded)} workspace(s) would be bound."))
            return

        # Seed once up front rather than letting the first workspace lazily do it.
        ensure_canonical_subscription_tiers()

        bound = 0
        for workspace in stranded:
            ensure_workspace_default_plan(workspace)
            workspace.refresh_from_db(fields=["plan"])
            if workspace.plan_id:
                bound += 1
                self.stdout.write(self.style.SUCCESS(f"Bound {workspace.id} → {workspace.plan.title}"))
            else:
                self.stderr.write(self.style.ERROR(f"Could not bind a plan to {workspace.id}"))

        self.stdout.write(
            self.style.NOTICE(f"Workspace plan backfill complete (bound={bound}, skipped={len(stranded) - bound}).")
        )
