"""Integration tests — the keyed chunk writer lands rows in ``ai_embedding_chunks``.

Verifies :class:`PgVectorCorpusChunkIndexAdapter` (the knowledge-owned write door
Remediation Memory embeds through, ADR 0012 P4) against the real ``EmbeddingChunk``
table. On SQLite (pytest skips migrations) the pgvector extension is absent, so the
vector is skipped best-effort and the row is still written with content + metadata —
which is exactly what these tests assert (write + idempotency + delete), independent
of the embeddings backend.
"""

from __future__ import annotations

import pytest

from components.knowledge.infrastructure.adapters.pgvector_corpus_chunk_index_adapter import (
    PgVectorCorpusChunkIndexAdapter,
)
from infrastructure.persistence.ai.models import EmbeddingChunk


@pytest.mark.django_db
class TestCorpusChunkIndexAdapter:
    def test_index_chunk_writes_row_with_metadata(self):
        adapter = PgVectorCorpusChunkIndexAdapter()

        written = adapter.index_chunk(
            document_key="remediation_entry:e1",
            content="Remediation for log_watch: add a casing alias",
            metadata={"chunk_type": "remediation_entry", "workspace_id": "ws-1", "finding_kind": "log_watch"},
        )

        assert written == 1
        rows = list(EmbeddingChunk.objects.filter(metadata__document_key="remediation_entry:e1"))
        assert len(rows) == 1
        meta = rows[0].metadata
        assert meta["chunk_type"] == "remediation_entry"
        assert meta["workspace_id"] == "ws-1"
        assert meta["document_key"] == "remediation_entry:e1"
        assert "casing alias" in rows[0].content

    def test_reindex_same_key_replaces_in_place(self):
        adapter = PgVectorCorpusChunkIndexAdapter()
        adapter.index_chunk(document_key="remediation_entry:e2", content="v1", metadata={"workspace_id": "ws-1"})
        adapter.index_chunk(document_key="remediation_entry:e2", content="v2", metadata={"workspace_id": "ws-1"})

        rows = list(EmbeddingChunk.objects.filter(metadata__document_key="remediation_entry:e2"))
        assert len(rows) == 1  # replaced, not duplicated (idempotent by key)
        assert rows[0].content == "v2"

    def test_empty_content_writes_nothing(self):
        adapter = PgVectorCorpusChunkIndexAdapter()
        assert adapter.index_chunk(document_key="remediation_entry:e3", content="  ", metadata={}) == 0
        assert not EmbeddingChunk.objects.filter(metadata__document_key="remediation_entry:e3").exists()

    def test_delete_by_key_removes_the_chunk(self):
        adapter = PgVectorCorpusChunkIndexAdapter()
        adapter.index_chunk(document_key="remediation_entry:e4", content="x", metadata={"workspace_id": "ws-1"})

        removed = adapter.delete_by_key(document_key="remediation_entry:e4")

        assert removed == 1
        assert not EmbeddingChunk.objects.filter(metadata__document_key="remediation_entry:e4").exists()
