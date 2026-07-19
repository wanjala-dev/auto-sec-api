"""Regression test for the PDF/document embedding store-split fix (2026-07-15).

Uploaded documents were embedded into LangChain PGVector's own tables, but the
agent retrieval stack (``PgVectorStoreAdapter``) reads the Django
``EmbeddingChunk`` model — so ``has_indexed_content`` always returned False and
every PDF/document chat 404'd with "No content found". These tests lock the
fix: ``index_documents`` must write ``EmbeddingChunk`` rows carrying the
``pdf_id`` / ``workspace_id`` / ``user_id`` metadata the retrieval adapter
filters on, so ``has_indexed_content`` (the exact gate ``PdfChatUseCase``
checks first) returns True.

Stubs the embedding provider (no OpenAI). ``_attach_vectors`` no-ops on the
SQLite test DB (no ``vector`` type) — that's fine, because the store-split bug
was in ``has_indexed_content``, which reads ``metadata`` only.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from components.knowledge.infrastructure.adapters.pgvector_document_indexer import (
    index_documents,
)
from components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter import (
    PgVectorStoreAdapter,
)
from infrastructure.persistence.ai.models import EmbeddingChunk


class _FakeEmbeddings:
    """Deterministic embeddings client — never hits the network."""

    def embed_documents(self, texts):
        return [[0.1] * 1536 for _ in texts]

    def embed_query(self, text):
        return [0.1] * 1536


def _docs(pdf_id="146", workspace_id="ws-1", user_id="user-1", n=3):
    return [
        Document(
            page_content=f"chunk {i} body text",
            metadata={
                "page": i,
                "text": f"chunk {i} body text",
                "pdf_id": pdf_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "type": "pdf",
                "status": "active",
            },
        )
        for i in range(n)
    ]


@pytest.fixture
def _stub_embeddings():
    with patch(
        "components.knowledge.infrastructure.factories.embeddings.factory.EmbeddingsFactory.create_embeddings",
        return_value=_FakeEmbeddings(),
    ):
        yield


@pytest.mark.django_db
class TestPgvectorDocumentIndexer:
    def test_writes_embedding_chunks_with_retrieval_metadata(self, _stub_embeddings):
        count = index_documents(_docs(pdf_id="146", workspace_id="ws-1", n=3))

        assert count == 3
        rows = list(EmbeddingChunk.objects.filter(metadata__pdf_id="146"))
        assert len(rows) == 3
        # Every row carries the keys PdfChatUseCase filters on.
        for row in rows:
            assert row.metadata["pdf_id"] == "146"
            assert row.metadata["workspace_id"] == "ws-1"
            assert row.metadata["user_id"] == "user-1"
            assert row.content

    def test_has_indexed_content_true_after_indexing(self, _stub_embeddings):
        """The exact gate that returned False before the fix (→ 404)."""
        adapter = PgVectorStoreAdapter()
        assert adapter.has_indexed_content(pdf_id="146", workspace_id="ws-1", user_id="user-1") is False

        index_documents(_docs(pdf_id="146", workspace_id="ws-1", user_id="user-1"))

        assert adapter.has_indexed_content(pdf_id="146", workspace_id="ws-1", user_id="user-1") is True

    def test_empty_documents_is_a_noop(self, _stub_embeddings):
        assert index_documents([]) == 0
        assert EmbeddingChunk.objects.count() == 0
