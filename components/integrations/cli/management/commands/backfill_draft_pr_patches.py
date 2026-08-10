"""Backfill the inline-reviewable patch onto LEGACY draft-PR records.

Findings whose draft PR was opened before the open step began persisting its
patch carry only a link, so the HUD callouts have no code to show. This command
reads each such PR's patch from its code host through the VCS port and writes it
back through the ``project``-owned recorder — after which legacy and new records
render identically.

Idempotent: a record that already carries a diff is skipped, so re-running is
free. Nothing is ever invented — an unreadable PR is skipped with a reason.

    # see what WOULD be filled, touching nothing
    python manage.py backfill_draft_pr_patches --dry-run

    # repair every workspace's legacy records
    python manage.py backfill_draft_pr_patches

    # scope to one workspace
    python manage.py backfill_draft_pr_patches --workspace <uuid>
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill the stored code diff onto draft-PR records opened before patches were persisted."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            default="",
            help="Limit the sweep to one workspace id (default: every workspace).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Maximum records to process in this run (default: 500).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read the patches and report what would be filled, without writing.",
        )

    def handle(self, *args, **options):
        from components.integrations.application.providers.vcs_provider import (
            get_backfill_draft_pr_patches_use_case,
        )

        dry_run = bool(options["dry_run"])
        report = get_backfill_draft_pr_patches_use_case().execute(
            workspace_id=str(options["workspace"] or ""),
            limit=int(options["limit"]),
            dry_run=dry_run,
        )

        if not report.outcomes:
            self.stdout.write("No legacy draft-PR records are missing a patch — nothing to do.")
            return

        for outcome in report.outcomes:
            if outcome.filled:
                marker = self.style.SUCCESS("FILLED ")
            elif outcome.reason == "dry_run":
                marker = self.style.NOTICE("WOULD  ")
            else:
                marker = self.style.WARNING("SKIPPED")
            detail = f"reason={outcome.reason}"
            if outcome.path:
                detail += f" path={outcome.path} diff_chars={outcome.diff_chars}"
            if outcome.pr_state:
                detail += f" pr_state={outcome.pr_state} merged={outcome.merged}"
            self.stdout.write(f"{marker} task={outcome.task_id} repo={outcome.repo} pr={outcome.pr_url} {detail}")

        if dry_run:
            resolvable = sum(1 for o in report.outcomes if o.reason == "dry_run")
            self.stdout.write(
                f"\n{len(report.outcomes)} record(s) examined — would fill {resolvable}, "
                f"cannot fill {len(report.outcomes) - resolvable}. Nothing was written."
            )
            return
        self.stdout.write(
            f"\n{len(report.outcomes)} record(s) examined — filled {report.filled}, skipped {report.skipped}."
        )
