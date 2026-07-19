"""Management command for the project-at-risk detector.

Usage:

    python manage.py run_project_at_risk_detector
    python manage.py run_project_at_risk_detector --workspace <uuid>
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Run the project-at-risk detector across all active workspaces, or "
        "a specific one with --workspace. Flags projects with 3+ overdue, "
        "non-done tasks."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            dest="workspace_id",
            default=None,
            help="Restrict to a single workspace UUID.",
        )

    def handle(self, *args, **options):
        from infrastructure.persistence.workspaces.models import Workspace
        from components.project.infrastructure.services.at_risk_detector_service import (
            report_at_risk_projects,
        )

        workspace_id = options.get("workspace_id")
        if workspace_id:
            workspace = Workspace.objects.filter(id=workspace_id).first()
            if workspace is None:
                self.stderr.write(
                    self.style.ERROR(f"Workspace {workspace_id} not found.")
                )
                return
            workspaces = [workspace]
        else:
            workspaces = list(Workspace.objects.filter(is_active=True).only("id"))

        self.stdout.write(
            f"Scanning {len(workspaces)} workspace(s) for at-risk projects..."
        )
        total_emitted = 0
        for workspace in workspaces:
            try:
                emitted = report_at_risk_projects(workspace)
            except Exception as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"  [error] workspace={workspace.id} — {exc}"
                    )
                )
                continue
            total_emitted += emitted
            if emitted:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  workspace={workspace.id} emitted={emitted}"
                    )
                )
        self.stdout.write(
            self.style.SUCCESS(f"Done. Total new findings: {total_emitted}")
        )
