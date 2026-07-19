"""Materialize pending sign-off items as AI-team Kanban tasks.

Projects each workspace's pending sign-off queue onto its Agents "AI
Findings" board (assigned to the workspace owner) and reconciles cards
whose artifact has left the pending set. Idempotent — safe to re-run.

Use for the demo backfill + ad-hoc runs; the periodic Celery task
``sign_off.materialize_pending_signoff_tasks`` does the same sweep on a
cadence.

Invocation::

    # One workspace
    docker exec compose-web-1 python manage.py materialize_signoff_tasks \
        --workspace-id <uuid>

    # All workspaces with an Agents team
    docker exec compose-web-1 python manage.py materialize_signoff_tasks --all
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Materialize pending sign-off items as tasks on each workspace's "
        "AI Findings Kanban board, assigned to the workspace owner. "
        "Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-id",
            dest="workspace_id",
            help="Materialize for a single workspace (UUID).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_workspaces",
            help="Materialize for every workspace that has an Agents team.",
        )

    def handle(self, *args, **options):
        workspace_id = options.get("workspace_id")
        all_workspaces = bool(options.get("all_workspaces"))

        if not workspace_id and not all_workspaces:
            raise CommandError("Pass either --workspace-id <uuid> or --all.")
        if workspace_id and all_workspaces:
            raise CommandError("Pass only one of --workspace-id / --all.")

        from components.sign_off.application.services.materialize_signoff_tasks import (
            materialize_all_pending_signoff_tasks,
            materialize_workspace_signoff_tasks,
        )

        if all_workspaces:
            totals = materialize_all_pending_signoff_tasks()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sweep complete — workspaces={totals['workspaces']} "
                    f"created={totals['created']} "
                    f"reconciled_accepted={totals['reconciled_accepted']} "
                    f"reconciled_dismissed={totals['reconciled_dismissed']} "
                    f"reconcile_skipped={totals['reconcile_skipped']} "
                    f"errors={totals['errors']}"
                )
            )
            return

        result = materialize_workspace_signoff_tasks(str(workspace_id))
        self.stdout.write(
            self.style.SUCCESS(
                f"Workspace {workspace_id} — created={result['created']} "
                f"reconciled_accepted={result['reconciled_accepted']} "
                f"reconciled_dismissed={result['reconciled_dismissed']} "
                f"reconcile_skipped={result['reconcile_skipped']}"
            )
        )
