"""Backfill default Kanban columns on every team that's missing them.

Historically some teams were created via paths that didn't call
``ensure_team_board_columns`` — e.g. personal-workspace scaffolding or
direct ORM creates in seeders. Those teams end up with an empty or
partial column set, which makes the project/task Kanban board render
empty even though projects exist (they have nowhere to land).

Run this manually when a user reports an empty Kanban board, or as a
one-off after deploying the default-column guarantee.

Usage:
    python manage.py backfill_team_board_columns
    python manage.py backfill_team_board_columns --workspace-id <uuid>
    python manage.py backfill_team_board_columns --team-id <id>
    python manage.py backfill_team_board_columns --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from components.workspace.application.facades.workspace_facade import (
    ensure_team_board_columns,
)
from infrastructure.persistence.project.models import Column
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace


class Command(BaseCommand):
    help = (
        "Ensure every team has the default Kanban columns "
        "(Backlog / Todo / In Progress / Testing / Complete / Canceled)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-id",
            type=str,
            help="Limit to teams in this workspace. Mutually exclusive with --team-id.",
        )
        parser.add_argument(
            "--team-id",
            type=str,
            help="Backfill a single team. Mutually exclusive with --workspace-id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report missing columns without creating them.",
        )

    def handle(self, *args, **options):
        workspace_id = options.get("workspace_id")
        team_id = options.get("team_id")
        dry_run = options.get("dry_run")

        if workspace_id and team_id:
            raise CommandError(
                "Pass either --workspace-id or --team-id, not both."
            )

        teams_qs = Team.objects.select_related("workspace", "workspace__workspace_owner")
        if team_id:
            teams_qs = teams_qs.filter(id=team_id)
        elif workspace_id:
            try:
                workspace = Workspace.objects.get(id=workspace_id)
            except Workspace.DoesNotExist as exc:
                raise CommandError(f"Workspace {workspace_id!r} not found.") from exc
            teams_qs = teams_qs.filter(workspace=workspace)

        totals = {"teams": 0, "updated": 0, "already_complete": 0, "no_owner": 0}

        for team in teams_qs.iterator(chunk_size=500):
            totals["teams"] += 1
            workspace = team.workspace
            if workspace is None:
                continue

            existing_titles = set(
                Column.objects.filter(workspace=workspace, team=team)
                .values_list("title", flat=True)
            )
            required_titles = {
                "Backlog", "Todo", "In Progress", "Testing", "Complete", "Canceled",
            }
            missing = required_titles - existing_titles
            if not missing:
                totals["already_complete"] += 1
                continue

            owner = getattr(workspace, "workspace_owner", None) or team.created_by
            if owner is None:
                totals["no_owner"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'team id={team.id} title={team.title!r} — missing {sorted(missing)} '
                        f'but no owner available; skipped.'
                    )
                )
                continue

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f'team id={team.id} title={team.title!r} missing {sorted(missing)}'
                    )
                )
                continue

            ensure_team_board_columns(workspace, team, owner)
            totals["updated"] += 1
            self.stdout.write(
                f'team id={team.id} title={team.title!r} added {sorted(missing)}'
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Summary: "
                f"teams={totals['teams']}, "
                f"updated={totals['updated']}, "
                f"already_complete={totals['already_complete']}, "
                f"no_owner={totals['no_owner']}"
            )
        )
