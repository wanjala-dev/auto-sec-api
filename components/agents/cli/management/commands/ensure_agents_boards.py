"""Idempotent backfill for the per-workspace Agents team + AI Findings board.

Phase 1 of the Agents-as-Teammates migration shipped data migration
``infrastructure.persistence.workspaces.migrations.0021_backfill_agents_board``
which calls ``ensure_agents_board`` for every active workspace. That
migration ran cleanly in CI but a 2026-06-06 production check found two
workspaces created on 2026-04-17 that the migration had silently
missed — likely a DB-restore-after-migration edge case where the
migration was marked applied before those rows existed in production.

The migration's logic is correct; replaying it would catch the gap.
But replaying data migrations is not the conventional flow — operators
need an ad-hoc tool. This command IS that tool:

* Idempotent (``ensure_agents_board`` is itself idempotent — calling on
  a workspace that already has its team is a no-op).
* Per-workspace failure isolation (one bad workspace doesn't void the
  rest of the sweep).
* ``--dry-run`` for inspection without writes.

Invocation::

    docker exec compose-web-1 python manage.py ensure_agents_boards
    docker exec compose-web-1 python manage.py ensure_agents_boards --dry-run

Use after:
* A production DB restore from a backup.
* Discovering drift in the per-workspace agent-team coverage.
* Any future change that adds a workspace-creation path the eager
  ``ensure_agents_board`` call hasn't yet been wired into.

See ``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md`` Phase 1.
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Ensure every active workspace has an Agents team + 'AI Findings' "
        "Kanban board. Idempotent — workspaces that already have the team "
        "are no-ops."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report which workspaces would be backfilled without "
                "making any database changes."
            ),
        )

    def handle(self, *args, **options):
        from infrastructure.persistence.team.models import Team
        from infrastructure.persistence.workspaces.models import Workspace

        from components.agents.application.facades.ai_teammate_facade import (
            ensure_agents_board,
        )

        dry_run = bool(options.get("dry_run"))

        active_ids = set(
            Workspace.objects.filter(is_active=True).values_list(
                "id", flat=True
            )
        )
        # ``kind=AI_AGENTS`` is the authoritative signal.
        # ``ensure_agents_team`` names the team after the workspace's AI
        # teammate (e.g. "Nematron", "Zy Ai"), then renames it whenever
        # the teammate's ``display_name`` changes. Filtering by
        # ``title="Agents"`` would miss every workspace whose teammate
        # has been renamed (which is most of production).
        already_provisioned = set(
            Team.objects.filter(
                kind=Team.Kind.AI_AGENTS,
                workspace_id__in=active_ids,
                status=Team.ACTIVE,
            ).values_list("workspace_id", flat=True)
        )
        missing_ids = active_ids - already_provisioned

        self.stdout.write(
            f"Active workspaces: {len(active_ids)}"
        )
        self.stdout.write(
            f"Already have Agents team: {len(already_provisioned)}"
        )
        self.stdout.write(
            f"Need backfill: {len(missing_ids)}"
        )

        if dry_run:
            for wid in missing_ids:
                self.stdout.write(f"  [dry-run] would backfill {wid}")
            return

        if not missing_ids:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        seeded = 0
        failed = 0
        for workspace in Workspace.objects.filter(id__in=missing_ids).iterator(
            chunk_size=100
        ):
            try:
                ensure_agents_board(workspace)
                seeded += 1
                self.stdout.write(
                    f"  OK backfilled {workspace.id} "
                    f"({workspace.workspace_name!r})"
                )
            except Exception:
                failed += 1
                logger.exception(
                    "ensure_agents_boards_backfill_failed workspace_id=%s",
                    workspace.id,
                )
                self.stdout.write(
                    self.style.ERROR(
                        f"  FAIL {workspace.id} "
                        f"({workspace.workspace_name!r}) — see logs"
                    )
                )

        msg = f"Backfill complete — seeded={seeded} failed={failed}"
        if failed:
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))
