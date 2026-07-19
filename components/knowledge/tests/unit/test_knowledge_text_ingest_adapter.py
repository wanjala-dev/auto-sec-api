"""Unit tests for ``KnowledgeTextIngestAdapter`` — provider resolution + dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from components.knowledge.infrastructure.adapters.knowledge_text_ingest_adapter import (
    KnowledgeTextIngestAdapter,
)


class TestProviderResolution:
    """The adapter no longer resolves a provider itself (2026-07-14): its
    old private env fallback defaulted to ELASTICSEARCH while retrieval
    used the factory's settings default (pgvector on the lean stack), so
    ingest and retrieval could land on DIFFERENT stores — report RAG
    indexing silently crashed wherever the env var was unset. ``None``
    now defers to ``VectorStoreFactory``'s settings-based resolution so
    both sides of the collection always agree."""

    def test_explicit_provider_wins(self):
        adapter = KnowledgeTextIngestAdapter(provider="pgvector")
        assert adapter._provider == "pgvector"

    def test_explicit_provider_is_lowercased(self):
        adapter = KnowledgeTextIngestAdapter(provider="PGVECTOR")
        assert adapter._provider == "pgvector"

    def test_none_defers_to_the_factory_default(self, monkeypatch):
        # No private resolution: the adapter stores None and passes it to
        # VectorStoreFactory.create_vector_store, whose settings-based
        # default keeps ingest + retrieval on the SAME store.
        monkeypatch.delenv("VECTOR_STORE_PROVIDER", raising=False)
        adapter = KnowledgeTextIngestAdapter()
        assert adapter._provider is None


class TestIndexTextDispatch:
    def test_empty_text_returns_zero_without_calling_factory(self):
        adapter = KnowledgeTextIngestAdapter(provider="pgvector")
        assert adapter.index_text(text="   ", document_key="k", metadata={}) == 0

    def test_missing_document_key_raises(self):
        adapter = KnowledgeTextIngestAdapter(provider="pgvector")
        with pytest.raises(ValueError, match="document_key is required"):
            adapter.index_text(text="hello", document_key="", metadata={})

    def test_index_text_uses_configured_provider_for_factory(self):
        adapter = KnowledgeTextIngestAdapter(provider="pgvector")
        with (
            patch(
                "components.knowledge.infrastructure.factories.vector_stores.factory.VectorStoreFactory.create_vector_store"
            ) as create_store,
            patch(
                "components.knowledge.infrastructure.factories.embeddings.factory.EmbeddingsFactory.create_embeddings"
            ) as create_embeddings,
            patch.object(adapter, "delete_by_key", return_value=0),
        ):
            fake_store = MagicMock()
            create_store.return_value = fake_store
            create_embeddings.return_value = MagicMock()

            chunks = adapter.index_text(
                text="hello world " * 50,
                document_key="report:ws:r1",
                metadata={"source": "financial_report"},
            )

        assert chunks >= 1
        create_store.assert_called_once()
        assert create_store.call_args.kwargs["provider"] == "pgvector"
        fake_store.add_documents.assert_called_once()


class TestDeleteByKeyDispatch:
    def test_empty_key_returns_zero(self):
        adapter = KnowledgeTextIngestAdapter(provider="pgvector")
        assert adapter.delete_by_key(document_key="") == 0

    def test_unknown_provider_is_noop(self):
        adapter = KnowledgeTextIngestAdapter(provider="unknown")
        assert adapter.delete_by_key(document_key="k") == 0

    def test_pgvector_delete_swallows_unsupported(self):
        adapter = KnowledgeTextIngestAdapter(provider="pgvector")
        with patch(
            "components.knowledge.infrastructure.factories.vector_stores.pgvector.build_pgvector_store"
        ) as build_store:
            fake_store = MagicMock()
            fake_store.delete.side_effect = NotImplementedError("old version")
            build_store.return_value = fake_store

            assert adapter.delete_by_key(document_key="k") == 0
            fake_store.delete.assert_called_once_with(filter={"document_key": "k"})
