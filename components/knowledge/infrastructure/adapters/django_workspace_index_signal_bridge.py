"""Signal bridge: Workspace.post_save → knowledge's reindex handler.

A dedicated bridge (with its own dispatch_uid) so it doesn't collide with
the workspace context's own ``post_save`` registration.  Bridges are
per-listener — multiple contexts can listen to the same sender, each with
their own uid.

Errors in the handler are logged but never propagated — a signal handler
that raises would otherwise abort the caller's save transaction.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save

from infrastructure.persistence.workspaces.models import Workspace

logger = logging.getLogger(__name__)


class DjangoWorkspaceIndexSignalBridge:
    """Registers a Workspace.post_save handler for the knowledge context."""

    DISPATCH_UID = "knowledge:workspace_reindex_on_save"

    def register(self, *, handler) -> None:
        post_save.connect(
            self._build_receiver(handler=handler),
            sender=Workspace,
            weak=False,
            dispatch_uid=self.DISPATCH_UID,
        )

    @staticmethod
    def _build_receiver(*, handler):
        def receiver(sender, instance, created, **kwargs):
            try:
                handler.execute(workspace=instance, created=created)
            except Exception:
                logger.exception(
                    "Knowledge workspace-reindex signal handler failed"
                )

        return receiver
