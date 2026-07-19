"""Unit tests for VectorStorePort hybrid search and scoped search."""

from components.knowledge.application.ports.vector_store_port import (
    RetrievedChunk,
    SearchMode,
    VectorStorePort,
)


class FakeVectorStore(VectorStorePort):
    """In-memory fake for testing port behaviour."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None):
        self._chunks = chunks or []

    def search(self, query, *, k=5, filters=None):
        # Simple keyword match for testing
        matched = [c for c in self._chunks if query.lower() in c.content.lower()]
        if filters:
            for key, value in filters.items():
                matched = [c for c in matched if c.metadata.get(key) == value]
        return matched[:k]

    def has_indexed_content(self, *, pdf_id=None, workspace_id=None, user_id=None):
        return len(self._chunks) > 0

    def provider_name(self):
        return "fake"


class TestHybridSearchFallback:
    def test_hybrid_search_defaults_to_search(self):
        chunks = [
            RetrievedChunk(content="Budget report for Q4", score=0.9),
            RetrievedChunk(content="Budget planning guide", score=0.7),
        ]
        store = FakeVectorStore(chunks)
        results = store.hybrid_search("budget", k=5, mode=SearchMode.HYBRID)
        assert len(results) == 2

    def test_hybrid_search_empty(self):
        store = FakeVectorStore([])
        results = store.hybrid_search("anything")
        assert results == []


class TestScopedSearch:
    def test_scoped_search_filters_by_agent_type(self):
        chunks = [
            RetrievedChunk(content="budget data", metadata={"agent_type": "budget_agent"}),
            RetrievedChunk(content="budget info", metadata={"agent_type": "workspace_agent"}),
        ]
        store = FakeVectorStore(chunks)
        results = store.scoped_search("budget", agent_type="budget_agent")
        assert len(results) == 1
        assert results[0].metadata["agent_type"] == "budget_agent"

    def test_scoped_search_filters_by_workspace(self):
        chunks = [
            RetrievedChunk(content="data for ws1", metadata={"workspace_id": "ws-1"}),
            RetrievedChunk(content="data for ws2", metadata={"workspace_id": "ws-2"}),
        ]
        store = FakeVectorStore(chunks)
        results = store.scoped_search("data", workspace_id="ws-1")
        assert len(results) == 1
        assert results[0].metadata["workspace_id"] == "ws-1"


class TestRerankerPort:
    def test_cross_encoder_reranker_fallback(self):
        """Test the keyword-overlap fallback reranker."""
        from components.knowledge.infrastructure.adapters.reranker.cross_encoder_reranker_adapter import (
            CrossEncoderRerankerAdapter,
        )

        reranker = CrossEncoderRerankerAdapter()
        chunks = [
            RetrievedChunk(content="The budget report shows growth in Q4 spending", score=0.5),
            RetrievedChunk(content="Unrelated content about weather patterns", score=0.8),
            RetrievedChunk(content="Budget planning for next fiscal year", score=0.3),
        ]
        results = reranker.rerank("budget report", chunks, top_k=2)
        assert len(results) == 2
        # The budget-related chunks should score higher than weather
        contents = [r.content for r in results]
        assert any("budget" in c.lower() for c in contents)
