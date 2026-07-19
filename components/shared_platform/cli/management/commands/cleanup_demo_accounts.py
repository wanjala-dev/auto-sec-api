"""Self-cleaning sweep of EXPIRED provisioned demo accounts.

Finds every ACTIVE ``DemoAccount`` whose ``expires_at`` is in the past and tears
each down via the shared ``teardown_demo_account`` service. This is the sweep the
Celery beat schedule will fire (wiring beat is a separate step — NOT done here).

Dry-run by DEFAULT — pass ``--apply`` to actually delete. Without ``--apply`` the
command only reports what would be removed, so a stray invocation cannot destroy
demo data.

Usage:
    python manage.py cleanup_demo_accounts            # dry run — reports only
    python manage.py cleanup_demo_accounts --apply    # actually tear down
    python manage.py cleanup_demo_accounts --apply --json
"""

from __future__ import annotations

import json
import logging

from django.apps import apps as django_apps
from django.core.management import BaseCommand
from django.utils import timezone

from components.shared_platform.infrastructure.services.demo_account_teardown import (
    sweep_expired_demo_accounts,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Tear down every ACTIVE demo account whose TTL has expired. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually tear down expired accounts (default is a dry run that only reports)",
        )
        parser.add_argument("--json", action="store_true", help="Emit a JSON result object")

    def handle(self, *args, **options):
        apply = options["apply"]
        as_json = options["json"]

        if not apply:
            self._emit_dry_run(as_json=as_json)
            return

        # Shared sweep — the single source of truth also used by the beat task.
        summary = sweep_expired_demo_accounts(apply=True, write=self.stdout.write)

        logger.info(
            "cleanup_demo_accounts swept found=%s torn_down=%s users_deleted=%s stripe_deferred=%s errors=%s",
            summary["found"],
            summary["torn_down"],
            summary["users_deleted"],
            summary["stripe_deferred"],
            summary["errors"],
        )

        if as_json:
            self.stdout.write(json.dumps(summary))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSwept expired demo accounts: found={summary['found']} "
                f"torn_down={summary['torn_down']} users_deleted={summary['users_deleted']} "
                f"stripe_deferred={summary['stripe_deferred']} errors={summary['errors']}"
            )
        )

    def _emit_dry_run(self, *, as_json: bool) -> None:
        DemoAccount = django_apps.get_model("core", "DemoAccount")
        expired = (
            DemoAccount.objects.filter(
                status=DemoAccount.Status.ACTIVE,
                expires_at__isnull=False,
                expires_at__lt=timezone.now(),
            )
            .exclude(is_canonical=True)  # canonical demos are never swept
            .select_related("workspace", "user")
            .iterator(chunk_size=500)
        )
        planned = [
            {
                "demo_account_id": account.id,
                "workspace_id": str(account.workspace_id),
                "workspace_name": account.workspace.workspace_name if account.workspace_id else "",
                "email": account.user.email if account.user_id else "",
                "expires_at": account.expires_at.isoformat() if account.expires_at else None,
                "stripe_deferred": (account.stripe_account_id or "").strip() or None,
            }
            for account in expired
        ]
        if as_json:
            self.stdout.write(json.dumps({"dry_run": True, "found": len(planned), "would_tear_down": planned}))
            return

        self.stdout.write(
            self.style.WARNING(
                f"\nDRY RUN — {len(planned)} expired demo account(s) WOULD be torn down (pass --apply to delete):"
            )
        )
        for item in planned:
            self.stdout.write(
                f"  demo_account_id={item['demo_account_id']} "
                f"workspace={item['workspace_name']} ({item['workspace_id']}) "
                f"email={item['email']} expired={item['expires_at']}"
            )
