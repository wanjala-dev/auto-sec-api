"""Management command: reindex one workspace or all active workspaces.

Usage::

    python manage.py reindex_workspaces --all            # every active workspace
    python manage.py reindex_workspaces --workspace ID   # just one
    python manage.py reindex_workspaces --all --force    # ignore content-hash skip
    python manage.py reindex_workspaces --all --sync     # run inline (no Celery)

The ``--sync`` mode is useful for a post-deploy backfill on EC2 where we
want to see results immediately, not scatter jobs across Celery workers.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Reindex workspace(s) into the pgvector store."

    def add_arguments(self, parser) -> None:
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument(
            "--all",
            action="store_true",
            help="Reindex every active workspace.",
        )
        scope.add_argument(
            "--workspace",
            dest="workspace_id",
            help="UUID of a single workspace to reindex.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-embed even if the content hash is unchanged.",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run inline instead of enqueueing Celery tasks.",
        )

    def handle(self, *args, **options) -> None:
        from components.knowledge.application.providers.workspace_index_provider import (
            workspace_index,
        )
        from components.knowledge.infrastructure.tasks.workspace_index_tasks import (
            reindex_all_workspaces,
            reindex_workspace,
        )
        from infrastructure.persistence.workspaces.models import Workspace

        force = bool(options.get("force"))
        sync = bool(options.get("sync"))

        if options.get("workspace_id"):
            workspace_id = options["workspace_id"]
            if not Workspace.objects.filter(id=workspace_id).exists():
                raise CommandError(f"Workspace {workspace_id} not found")

            if sync:
                result = workspace_index().reindex(workspace_id, force=force)
                self.stdout.write(
                    f"workspace={workspace_id} status={result.status} "
                    f"chunks={result.chunks_written} hash={result.content_hash[:12]}"
                )
            else:
                task = reindex_workspace.delay(workspace_id, force)
                self.stdout.write(
                    f"queued workspace={workspace_id} task_id={task.id}"
                )
            return

        if options.get("all"):
            if sync:
                adapter = workspace_index()
                totals = {"indexed": 0, "skipped": 0, "empty": 0, "failed": 0}
                for workspace_id in Workspace.objects.filter(
                    is_active=True
                ).values_list("id", flat=True):
                    result = adapter.reindex(str(workspace_id), force=force)
                    totals[result.status] = totals.get(result.status, 0) + 1
                    self.stdout.write(
                        f"  {workspace_id} → {result.status} "
                        f"(chunks={result.chunks_written})"
                    )
                self.stdout.write(self.style.SUCCESS(f"Done: {totals}"))
            else:
                task = reindex_all_workspaces.delay(force)
                self.stdout.write(
                    f"queued reindex_all_workspaces task_id={task.id}"
                )
            return
