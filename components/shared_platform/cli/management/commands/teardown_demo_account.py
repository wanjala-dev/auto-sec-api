"""Tear down one or more provisioned demo accounts by explicit selector.

Resolves the matching ACTIVE ``DemoAccount`` row(s) via exactly one selector
(``--id`` / ``--workspace-id`` / ``--email``) and tears each down via the shared
``teardown_demo_account`` service (workspace delete + CASCADE + orphan-user
cleanup). ``--dry-run`` prints what WOULD be removed without deleting anything.

Usage:
    python manage.py teardown_demo_account --workspace-id <uuid>
    python manage.py teardown_demo_account --email demo.admin@example.com --dry-run
    python manage.py teardown_demo_account --id 42 --json
"""

from __future__ import annotations

import json
import logging

from django.apps import apps as django_apps
from django.core.management import BaseCommand, CommandError

from components.shared_platform.infrastructure.services.demo_account_teardown import (
    teardown_demo_account,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Tear down provisioned demo account(s) selected by --id / --workspace-id / --email."

    def add_arguments(self, parser):
        parser.add_argument("--id", dest="demo_account_id", help="DemoAccount primary key")
        parser.add_argument("--workspace-id", dest="workspace_id", help="Workspace UUID")
        parser.add_argument("--email", help="Owner email (may match several active demo accounts)")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what WOULD be torn down without deleting anything",
        )
        parser.add_argument("--json", action="store_true", help="Emit a JSON result object")

    def handle(self, *args, **options):
        DemoAccount = django_apps.get_model("core", "DemoAccount")

        demo_account_id = options.get("demo_account_id")
        workspace_id = options.get("workspace_id")
        email = options.get("email")
        dry_run = options["dry_run"]
        as_json = options["json"]

        selectors = [s for s in (demo_account_id, workspace_id, email) if s]
        if not selectors:
            raise CommandError("One selector is required: --id, --workspace-id, or --email")
        if len(selectors) > 1:
            raise CommandError("Pass exactly ONE selector: --id, --workspace-id, or --email")

        accounts = DemoAccount.objects.filter(status=DemoAccount.Status.ACTIVE)
        if demo_account_id:
            accounts = accounts.filter(id=demo_account_id)
        elif workspace_id:
            accounts = accounts.filter(workspace_id=workspace_id)
        else:
            accounts = accounts.filter(user__email=email)

        accounts = list(accounts.select_related("workspace", "user"))
        if not accounts:
            raise CommandError("No active demo account matched the selector")

        if dry_run:
            self._emit_dry_run(accounts, as_json=as_json)
            return

        summaries = [teardown_demo_account(account, write=self.stdout.write) for account in accounts]
        self._emit_summaries(summaries, as_json=as_json)

    def _emit_dry_run(self, accounts, *, as_json: bool) -> None:
        planned = [
            {
                "demo_account_id": account.id,
                "workspace_id": str(account.workspace_id),
                "workspace_name": account.workspace.workspace_name if account.workspace_id else "",
                "email": account.user.email if account.user_id else "",
                "stripe_deferred": (account.stripe_account_id or "").strip() or None,
            }
            for account in accounts
        ]
        if as_json:
            self.stdout.write(json.dumps({"dry_run": True, "would_tear_down": planned}))
            return

        self.stdout.write(self.style.WARNING(f"\nDRY RUN — would tear down {len(planned)} demo account(s):"))
        for item in planned:
            self.stdout.write(
                f"  demo_account_id={item['demo_account_id']} "
                f"workspace={item['workspace_name']} ({item['workspace_id']}) email={item['email']}"
            )

    def _emit_summaries(self, summaries: list[dict], *, as_json: bool) -> None:
        if as_json:
            self.stdout.write(json.dumps({"torn_down": summaries}))
            return

        self.stdout.write(self.style.SUCCESS(f"\nTore down {len(summaries)} demo account(s):"))
        for summary in summaries:
            self.stdout.write(
                f"  workspace={summary['workspace_name']} ({summary['workspace_id']}) "
                f"workspace_deleted={summary['workspace_deleted']} user_deleted={summary['user_deleted']} "
                f"stripe_deferred={summary['stripe_deferred'] or '-'}"
            )
