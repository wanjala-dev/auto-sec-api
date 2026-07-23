"""Backfill the provenance graph for a workspace from the internal audit trail.

Usage:
    python manage.py backfill_provenance --workspace-id <uuid> [--since 2026-07-01]
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from components.provenance.infrastructure.services.audit_backfill_service import (
    backfill_from_audit_log,
)
from components.provenance.infrastructure.services.identity_backfill_service import (
    backfill_from_memberships,
)


class Command(BaseCommand):
    help = "Project internal sources (audit trail + memberships) into the provenance graph."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", required=True, help="Workspace UUID to backfill.")
        parser.add_argument("--since", default=None, help="ISO datetime lower bound for audit events (optional).")

    def handle(self, *args, **options):
        workspace_id = options["workspace_id"]
        since = None
        if options["since"]:
            try:
                since = datetime.fromisoformat(options["since"])
            except ValueError as exc:
                raise CommandError(f"--since must be ISO format: {exc}") from exc

        audit = backfill_from_audit_log(workspace_id=workspace_id, since=since)
        identity = backfill_from_memberships(workspace_id=workspace_id)
        self.stdout.write(
            self.style.SUCCESS(
                "provenance backfill complete "
                f"audit(scanned={audit['scanned']} actors={audit['actors']} "
                f"resources={audit['resources']} events={audit['events']}) "
                f"identity(scanned={identity['scanned']} actors={identity['actors']} "
                f"resources={identity['resources']} grants={identity['grants']})"
            )
        )
