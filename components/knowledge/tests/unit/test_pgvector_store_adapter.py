"""Unit tests for PgVectorStoreAdapter.

These tests mock Django's database cursor so they run without
a real PostgreSQL instance or pgvector extension.
"""

from unittest.mock import MagicMock, patch

import pytest

from components.knowledge.application.ports.vector_store_port import RetrievedChunk, SearchMode
from components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter import (
    PgVectorStoreAdapter,
)


@pytest.fixture
def adapter():
    return PgVectorStoreAdapter()


class TestProviderName:
    def test_returns_pgvector(self, adapter):
        assert adapter.provider_name() == "pgvector"


class TestBuildFilterClause:
    def test_empty_filters(self, adapter):
        sql, params = adapter._build_filter_clause(None)
        assert sql == ""
        assert params == []

    def test_single_filter(self, adapter):
        sql, params = adapter._build_filter_clause({"pdf_id": "abc-123"})
        assert "metadata->>%s = %s" in sql
        assert params == ["pdf_id", "abc-123"]

    def test_multiple_filters(self, adapter):
        sql, params = adapter._build_filter_clause({"pdf_id": "abc", "workspace_id": "ws-1"})
        assert sql.count("metadata->>%s = %s") == 2
        assert len(params) == 4


class TestSearch:
    @patch("components.knowledge.infrastructure.factories.embeddings.factory.EmbeddingsFactory")
    @patch("django.db.connection")
    def test_search_returns_retrieved_chunks(self, mock_conn, mock_factory, adapter):
        # Mock embeddings
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1] * 1536
        mock_factory.create_embeddings.return_value = mock_embeddings

        # Mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Budget report Q4", {"pdf_id": "abc"}, 0.92),
            ("Budget planning", {"pdf_id": "abc"}, 0.85),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = adapter.search("budget", k=2, filters={"pdf_id": "abc"})

        assert len(results) == 2
        assert isinstance(results[0], RetrievedChunk)
        assert results[0].content == "Budget report Q4"
        assert results[0].score == 0.92
        assert results[0].metadata == {"pdf_id": "abc"}

    @patch("components.knowledge.infrastructure.factories.embeddings.factory.EmbeddingsFactory")
    @patch("django.db.connection")
    def test_search_empty_results(self, mock_conn, mock_factory, adapter):
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.0] * 1536
        mock_factory.create_embeddings.return_value = mock_embeddings

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = adapter.search("nonexistent")
        assert results == []


class TestHasIndexedContent:
    @patch("infrastructure.persistence.ai.models.EmbeddingChunk")
    def test_returns_true_when_chunks_exist(self, mock_model, adapter):
        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.exists.return_value = True
        mock_model.objects.all.return_value = mock_qs

        assert adapter.has_indexed_content(pdf_id="abc") is True

    @patch("infrastructure.persistence.ai.models.EmbeddingChunk")
    def test_returns_false_when_no_chunks(self, mock_model, adapter):
        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.exists.return_value = False
        mock_model.objects.all.return_value = mock_qs

        assert adapter.has_indexed_content(workspace_id="ws-1") is False


class TestHybridSearch:
    @patch("components.knowledge.infrastructure.factories.embeddings.factory.EmbeddingsFactory")
    @patch("django.db.connection")
    def test_keyword_mode_uses_keyword_search(self, mock_conn, mock_factory, adapter):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Budget keyword match", {}, 0.5),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = adapter.hybrid_search("budget", mode=SearchMode.KEYWORD)
        assert len(results) == 1

        # Verify the SQL used tsvector (keyword search) and NOT pgvector
        # similarity. The `ai_embedding_chunks` table name contains the
        # substring "embedding", so assert on the `<=>` distance operator,
        # which only the vector path uses.
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "to_tsvector" in executed_sql
        assert "<=>" not in executed_sql

    @patch("components.knowledge.infrastructure.factories.embeddings.factory.EmbeddingsFactory")
    @patch("django.db.connection")
    def test_hybrid_mode_combines_signals(self, mock_conn, mock_factory, adapter):
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1] * 1536
        mock_factory.create_embeddings.return_value = mock_embeddings

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("Combined result", {}, 0.78),
        ]
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        results = adapter.hybrid_search(
            "budget",
            mode=SearchMode.HYBRID,
            vector_weight=0.6,
            keyword_weight=0.4,
        )
        assert len(results) == 1

        # Verify the SQL combines both signals: tsvector (keyword) AND the
        # pgvector `<=>` distance operator (vector similarity).
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "<=>" in executed_sql
        assert "to_tsvector" in executed_sql


class TestVectorStoreProviderRegistration:
    def test_pgvector_registered_in_provider(self):
        from components.knowledge.application.providers.ai_vector_store_provider import (
            AIVectorStoreProvider,
        )

        provider = AIVectorStoreProvider()
        available = provider.available_providers()
        assert "pgvector" in available
        assert "postgres" in available

    def test_get_pgvector_port(self):
        from components.knowledge.application.providers.ai_vector_store_provider import (
            AIVectorStoreProvider,
        )

        provider = AIVectorStoreProvider()
        adapter = provider.get_port("pgvector")
        assert adapter.provider_name() == "pgvector"
