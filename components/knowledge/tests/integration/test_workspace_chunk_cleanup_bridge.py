"""Integration tests for the Workspace post_delete chunk cleanup bridge.

Pin the lifecycle correctness contract: deleting a Workspace must
cascade to delete every EmbeddingChunk whose ``metadata.workspace_id``
matches. Today the chunks orphan because ``EmbeddingChunk`` has no
Django FK — the bridge runs the cleanup manually on ``post_delete``.

Tier 3 #14 audit (2026-06-11).
"""
from __future__ import annotations

import pytest


@pytest.mark.django_db
class TestWorkspaceChunkCleanupOnDelete:
    def test_chunks_deleted_when_workspace_deleted(
        self, workspace_factory
    ):
        from infrastructure.persistence.ai.models import EmbeddingChunk

        ws = workspace_factory()
        # Manually seed a chunk that should disappear.
        EmbeddingChunk.objects.create(
            content="x",
            metadata={"workspace_id": str(ws.id), "source": "workspace_snapshot"},
        )
        assert EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(ws.id)
        ).exists()

        ws.delete()

        assert not EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(ws.id)
        ).exists(), (
            "Workspace.post_delete must cascade-delete its index chunks. "
            "EmbeddingChunk has no FK to Workspace so the bridge does "
            "this manually — a regression here orphans chunks in prod."
        )

    def test_other_workspace_chunks_untouched(
        self, workspace_factory
    ):
        """The cleanup MUST be scoped to the deleted workspace.
        Deleting workspace A cannot wipe workspace B's chunks."""
        from infrastructure.persistence.ai.models import EmbeddingChunk

        ws_a = workspace_factory()
        ws_b = workspace_factory()
        EmbeddingChunk.objects.create(
            content="a", metadata={"workspace_id": str(ws_a.id)}
        )
        EmbeddingChunk.objects.create(
            content="b", metadata={"workspace_id": str(ws_b.id)}
        )

        ws_a.delete()

        assert not EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(ws_a.id)
        ).exists()
        # Workspace B's chunk survives.
        assert EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(ws_b.id)
        ).exists()

    def test_no_chunks_no_crash(self, workspace_factory):
        """A workspace with no chunks must delete cleanly — the
        bridge should silently no-op, not raise."""
        ws = workspace_factory()
        # No chunks created.
        ws.delete()  # should not raise


@pytest.mark.django_db
class TestDocumentChunkCleanupOnDelete:
    """Document post_delete must cascade to its embedding chunks too.

    The Document → EmbeddingChunk relationship lives in
    ``metadata.document_id`` (JSON), not a Django FK. Same gap as
    Workspace, same fix.
    """

    def test_chunks_deleted_when_document_deleted(
        self, workspace_factory
    ):
        from infrastructure.persistence.ai.models import (
            Document,
            EmbeddingChunk,
        )

        ws = workspace_factory()
        doc = Document.objects.create(
            workspace=ws,
            title="d",
            content="x",
            source="t",
            metadata={"workspace_id": str(ws.id)},
        )
        EmbeddingChunk.objects.create(
            content="d-chunk",
            metadata={"document_id": str(doc.id)},
        )
        assert EmbeddingChunk.objects.filter(
            metadata__document_id=str(doc.id)
        ).exists()

        doc.delete()

        assert not EmbeddingChunk.objects.filter(
            metadata__document_id=str(doc.id)
        ).exists()

    def test_other_document_chunks_untouched(
        self, workspace_factory
    ):
        from infrastructure.persistence.ai.models import (
            Document,
            EmbeddingChunk,
        )

        ws = workspace_factory()
        a = Document.objects.create(
            workspace=ws, title="a", content="x", source="t", metadata={}
        )
        b = Document.objects.create(
            workspace=ws, title="b", content="x", source="t", metadata={}
        )
        EmbeddingChunk.objects.create(
            content="a-chunk", metadata={"document_id": str(a.id)}
        )
        EmbeddingChunk.objects.create(
            content="b-chunk", metadata={"document_id": str(b.id)}
        )

        a.delete()

        assert not EmbeddingChunk.objects.filter(
            metadata__document_id=str(a.id)
        ).exists()
        assert EmbeddingChunk.objects.filter(
            metadata__document_id=str(b.id)
        ).exists()
