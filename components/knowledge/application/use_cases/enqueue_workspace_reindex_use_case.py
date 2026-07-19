"""Use case: enqueue a workspace reindex from a signal.

The use case is the application-layer entry point the signal bridge calls.
It has one job: hand off to the Celery task.  Any batching, debouncing, or
policy should live here — today it's a straight passthrough so the
adapter's content-hash skip does the work.

Framework-free at the application layer: the task import is deferred to
avoid pulling Celery into import-time during tests that don't need it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EnqueueWorkspaceReindexUseCase:
    """Signal handler entry point — enqueues the reindex Celery task."""

    def execute(self, *, workspace, created: bool) -> None:
        from components.knowledge.infrastructure.tasks.workspace_index_tasks import (
            reindex_workspace,
        )

        workspace_id = str(getattr(workspace, "id", "") or "")
        if not workspace_id:
            logger.debug("Skipping reindex enqueue: workspace has no id")
            return

        logger.debug(
            "Enqueueing reindex_workspace workspace_id=%s created=%s",
            workspace_id,
            created,
        )
        reindex_workspace.delay(workspace_id, False)
