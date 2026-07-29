"""Ensure every workspace has its Blue (default) + Red security teams (ADR 0007).

The 0005 data migration only *promotes* an existing default team and seeds Red
alongside it — a workspace that never had a default/home team (demo drift, or an
org whose only team was auto-created by the AI-teammate system) gets nothing.
This command closes that gap: it runs the real bootstrap scaffolding
(``ensure_workspace_scaffolding``) for every workspace, which CREATES the Blue
default team when missing, seeds the Red team, wires owner membership, and
provisions each team's board columns.

Idempotent (the scaffolding prefers an existing default team and one Red team per
workspace); safe to re-run and to wire into boot seeding. Findings/assets are
never touched — they stay the workspace-scoped SSOT (ADR 0004).

    python manage.py seed_security_teams            # all workspaces
    python manage.py seed_security_teams --workspace <uuid>
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from components.workspace.infrastructure.adapters.workspace_utils import (
    ensure_workspace_scaffolding,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Ensure every workspace has its Blue (default) + Red teams (ADR 0007)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            dest="workspace_id",
            default=None,
            help="Seed a single workspace by id (default: all workspaces).",
        )

    def handle(self, *args, **options):
        qs = Workspace.objects.all()
        if options["workspace_id"]:
            qs = qs.filter(id=options["workspace_id"])

        seeded = skipped = 0
        for workspace in qs.select_related("workspace_owner").iterator(chunk_size=200):
            owner = workspace.workspace_owner
            if owner is None:
                # No owner to lead the teams — bootstrap will seed on next access.
                skipped += 1
                self.stdout.write(f"  skip (no owner): {workspace.id}")
                continue
            ensure_workspace_scaffolding(workspace, owner)
            blue = Team.objects.filter(workspace=workspace, kind=Team.Kind.BLUE_TEAM, is_default=True).first()
            red = Team.objects.filter(workspace=workspace, kind=Team.Kind.RED_TEAM).first()
            seeded += 1
            self.stdout.write(f"  ok: {workspace.id} blue={'y' if blue else 'n'} red={'y' if red else 'n'}")

        self.stdout.write(self.style.SUCCESS(f"Security teams seeded: {seeded} workspace(s), {skipped} skipped."))
