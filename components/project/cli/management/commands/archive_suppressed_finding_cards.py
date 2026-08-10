"""Backfill: archive the board cards of already-SUPPRESSED findings.

The event-driven rule (``handle_finding_resolved_board``) archives a card the
moment its finding is suppressed — but findings suppressed BEFORE that rule
shipped (e.g. the ~9k demo-noise findings bulk-suppressed on 2026-08-09) left
their cards sitting in the Suggested intake lane. This command replays the same
transition for them: every suppressed finding's live card goes through the SAME
``ArchiveFindingCardsUseCase`` the event handler uses — recycle-bin tombstone +
provenance comment, never a delete, no raw SQL.

Idempotent: archived cards are excluded from the lookup, so a re-run archives
nothing twice (it reports already_archived / no-card counts instead).

Usage:
    manage.py archive_suppressed_finding_cards [--workspace <uuid>] [--dry-run]
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Archive board cards of suppressed findings into the recycle bin (reason-stamped, restorable)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            default=None,
            help="Limit to one workspace id (default: every workspace with suppressed findings).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the counts without archiving anything.",
        )

    def handle(self, *args, **options):
        from django.db.models import Q

        from components.agents.application.providers.agent_permissions_provider import (
            get_agent_permissions_provider,
        )
        from components.project.application.ports.archive_finding_cards_port import (
            ArchiveFindingCardsCommand,
        )
        from components.project.application.providers.project_provider import ProjectProvider
        from infrastructure.persistence.findings.models import Finding
        from infrastructure.persistence.project.models import Task
        from infrastructure.persistence.workspaces.models import Workspace

        workspace_id = options.get("workspace")
        dry_run = bool(options.get("dry_run"))

        findings = Finding.objects.filter(status="suppressed")
        if workspace_id:
            findings = findings.filter(workspace_id=workspace_id)
        total = findings.count()
        self.stdout.write(f"suppressed findings in scope: {total}")

        use_case = ProjectProvider.build_archive_finding_cards_use_case()
        provider = get_agent_permissions_provider()
        ai_user_by_ws: dict[str, object] = {}

        processed = 0
        archived_cards = 0
        already_archived = 0
        no_card = 0
        failed = 0

        for finding in findings.select_related("workspace").iterator(chunk_size=500):
            processed += 1
            if dry_run:
                lookup = Q(metadata__payload__finding_id=str(finding.id))
                if finding.fingerprint:
                    lookup |= Q(metadata__payload__lookup_key=finding.fingerprint)
                live = (
                    Task.objects.filter(workspace_id=finding.workspace_id)
                    .filter(lookup)
                    .exclude(status=Task.ARCHIVED)
                    .count()
                )
                archived_cards += live
                if live == 0:
                    no_card += 1
                continue

            try:
                ws_key = str(finding.workspace_id)
                ai_user = ai_user_by_ws.get(ws_key)
                if ai_user is None:
                    workspace = Workspace.objects.get(pk=finding.workspace_id)
                    _profile, ai_user = provider.ensure_ai_identity(workspace)
                    ai_user_by_ws[ws_key] = ai_user

                result = use_case.execute(
                    command=ArchiveFindingCardsCommand(
                        workspace_id=finding.workspace_id,
                        finding_id=str(finding.id),
                        fingerprint=finding.fingerprint or "",
                        reason="suppressed",
                        detail=finding.status_reason or "",
                        archived_by=ai_user.id,
                        actor_label="system:suppressed_cards_backfill",
                    )
                )
                archived_cards += result.archived_count
                already_archived += result.already_archived
                if result.archived_count == 0 and result.already_archived == 0:
                    no_card += 1
            except Exception:
                # Log-and-continue per-item (the bulk-loop pattern) — one broken
                # card must not strand the rest of the backfill.
                failed += 1
                logger.exception(
                    "suppressed_card_backfill_item_failed workspace_id=%s finding_id=%s",
                    finding.workspace_id,
                    finding.id,
                )

            if processed % 500 == 0:
                self.stdout.write(f"  … {processed}/{total} findings (archived {archived_cards} cards so far)")

        mode = "DRY RUN — would archive" if dry_run else "archived"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} {archived_cards} card(s) across {processed} suppressed finding(s); "
                f"already_archived={already_archived} no_live_card={no_card} failed={failed}"
            )
        )
