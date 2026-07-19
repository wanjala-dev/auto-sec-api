"""Tier 3 #14 — Document.post_delete → cascade-delete its index chunks.

Same shape as the Workspace bridge: Documents own embedding chunks
via a JSON ``metadata.document_id`` pointer, not a Django FK. When
a Document is deleted, its chunks orphan in the index.

The bridge wires ``post_delete`` on Document to delete every chunk
whose ``metadata.document_id`` matches. Two cleanup paths in the
same body of work because both have the same correctness problem
but different sender models.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete

logger = logging.getLogger(__name__)

_DISPATCH_UID = "knowledge:document_index_cleanup_on_delete"


class DjangoDocumentChunkCleanupSignalBridge:
    """Wires Document post_delete to the chunk-cleanup callback."""

    @staticmethod
    def register() -> None:
        from infrastructure.persistence.ai.models import Document

        post_delete.connect(
            _receiver,
            sender=Document,
            weak=False,
            dispatch_uid=_DISPATCH_UID,
        )
        logger.debug(
            "knowledge: registered Document.post_delete chunk-cleanup "
            "bridge dispatch_uid=%s",
            _DISPATCH_UID,
        )


def _receiver(sender, instance, **kwargs):  # noqa: ARG001
    document_id = getattr(instance, "id", None)
    if not document_id:
        return
    transaction.on_commit(lambda: _cleanup_chunks(str(document_id)))


def _cleanup_chunks(document_id: str) -> None:
    """Delete every EmbeddingChunk whose metadata names this document.

    The Document → EmbeddingChunk relationship lives in
    ``metadata.document_id``. The filter matches both PDF chunks
    (source="pdf") and other uploaded-document chunks.
    """
    try:
        from infrastructure.persistence.ai.models import EmbeddingChunk

        deleted, _ = EmbeddingChunk.objects.filter(
            metadata__document_id=document_id
        ).delete()
        if deleted:
            logger.info(
                "knowledge: cascaded EmbeddingChunk delete on document "
                "delete document_id=%s rows_deleted=%s",
                document_id,
                deleted,
            )
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "knowledge: chunk cleanup failed for deleted document "
            "document_id=%s — rows orphaned, run a manual cleanup",
            document_id,
        )
