"""SEE-205 — surface perceived-error findings from recent conversations.

Thin CLI/Celery entry point over
``perceived_error_scan.scan_workspace_for_perceived_errors``. Runs for one
workspace (``--workspace``) or all workspaces.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Scan recent conversations for perceived-error signals and surface findings."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", dest="workspace_id", default=None)
        parser.add_argument("--lookback-hours", dest="lookback_hours", type=int, default=24)

    def handle(self, *args, **options):
        from components.agents.infrastructure.services.perceived_error_scan import (
            scan_workspace_for_perceived_errors,
        )
        from infrastructure.persistence.workspaces.models import Workspace

        workspace_id = options.get("workspace_id")
        lookback_hours = options.get("lookback_hours") or 24

        if workspace_id:
            workspace_ids = [workspace_id]
        else:
            workspace_ids = list(
                Workspace.objects.values_list("id", flat=True).iterator(chunk_size=500)
            )

        total = 0
        for wid in workspace_ids:
            total += scan_workspace_for_perceived_errors(wid, lookback_hours=lookback_hours)

        self.stdout.write(
            f"perceived-error scan complete: {total} finding(s) "
            f"across {len(workspace_ids)} workspace(s)"
        )
