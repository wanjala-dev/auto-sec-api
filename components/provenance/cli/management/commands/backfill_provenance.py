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


class Command(BaseCommand):
    help = "Project EntityAuditLog rows into the provenance graph for a workspace."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", required=True, help="Workspace UUID to backfill.")
        parser.add_argument("--since", default=None, help="ISO datetime lower bound (optional).")

    def handle(self, *args, **options):
        since = None
        if options["since"]:
            try:
                since = datetime.fromisoformat(options["since"])
            except ValueError as exc:
                raise CommandError(f"--since must be ISO format: {exc}") from exc

        counts = backfill_from_audit_log(workspace_id=options["workspace_id"], since=since)
        self.stdout.write(
            self.style.SUCCESS(
                "provenance backfill complete "
                f"scanned={counts['scanned']} actors={counts['actors']} "
                f"resources={counts['resources']} events={counts['events']}"
            )
        )
