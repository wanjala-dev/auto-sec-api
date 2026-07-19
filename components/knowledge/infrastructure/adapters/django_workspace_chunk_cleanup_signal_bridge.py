"""Tier 3 #14 — Workspace.post_delete → cascade-delete its index chunks.

``EmbeddingChunk`` (the pgvector chunk store) is NOT a Django FK to
Workspace — its tenant scope lives in ``metadata.workspace_id``
(JSON column). Django's cascade machinery has nothing to follow, so
deleting a Workspace leaves every chunk it owned orphaned in the
table.

This bridge wires ``post_delete`` on Workspace to a callback that
deletes every chunk whose ``metadata.workspace_id`` matches. Runs
inside ``transaction.on_commit`` so the chunk DELETE doesn't fire
mid-rollback if the Workspace delete transaction unwinds.

Failure isolation: any exception in the chunk delete is logged and
swallowed. The Workspace delete itself has already committed by
the time on_commit fires; raising here would not roll it back, just
crash a worker thread and leave the chunks orphaned anyway.

Same pattern as the existing reindex bridges — see
``django_domain_change_reindex_signal_bridge.py``. Two file split
on purpose: this one watches Workspace, the next one watches
Document. Different sender, different cleanup semantics.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete

logger = logging.getLogger(__name__)

_DISPATCH_UID = "knowledge:workspace_index_cleanup_on_delete"


class DjangoWorkspaceChunkCleanupSignalBridge:
    """Wires Workspace post_delete to the chunk-cleanup callback."""

    @staticmethod
    def register() -> None:
        from infrastructure.persistence.workspaces.models import Workspace

        post_delete.connect(
            _receiver,
            sender=Workspace,
            weak=False,
            dispatch_uid=_DISPATCH_UID,
        )
        logger.debug(
            "knowledge: registered Workspace.post_delete chunk-cleanup "
            "bridge dispatch_uid=%s",
            _DISPATCH_UID,
        )


def _receiver(sender, instance, **kwargs):  # noqa: ARG001
    workspace_id = getattr(instance, "id", None)
    if not workspace_id:
        return
    transaction.on_commit(lambda: _cleanup_chunks(str(workspace_id)))


def _cleanup_chunks(workspace_id: str) -> None:
    """Delete every EmbeddingChunk whose metadata names this workspace.

    Covers both the workspace-snapshot chunks (source="workspace_snapshot")
    and any document-upload chunks that were written into the same
    table. The filter is the JSON ``metadata__workspace_id`` lookup —
    same shape the existing index adapter uses for read/write.
    """
    try:
        from infrastructure.persistence.ai.models import EmbeddingChunk

        deleted, _ = EmbeddingChunk.objects.filter(
            metadata__workspace_id=workspace_id
        ).delete()
        if deleted:
            logger.info(
                "knowledge: cascaded EmbeddingChunk delete on workspace "
                "delete workspace_id=%s rows_deleted=%s",
                workspace_id,
                deleted,
            )
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "knowledge: chunk cleanup failed for deleted workspace "
            "workspace_id=%s — rows orphaned, run a manual cleanup",
            workspace_id,
        )
