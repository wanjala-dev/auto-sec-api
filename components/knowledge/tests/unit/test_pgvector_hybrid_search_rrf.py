"""Tier 3 #11 — unit tests for Reciprocal Rank Fusion + hybrid_search_rrf.

The fusion helper ``_merge_via_rrf`` is pure logic and tested
directly.  ``hybrid_search_rrf`` is tested with the vector and
keyword half-paths stubbed, so we cover the orchestration without
a live Postgres connection:

* Both rankers contribute → RRF merges by rank.
* Keyword search returns empty → pure-vector top-k.
* Keyword search raises → pure-vector top-k.
* Embedding fails → keyword-only path.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #11.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from components.knowledge.application.ports.vector_store_port import RetrievedChunk
from components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter import (
    PgVectorStoreAdapter,
    _merge_via_rrf,
)


def _c(content: str, score: float = 0.0) -> RetrievedChunk:
    return RetrievedChunk(content=content, metadata={}, score=score)


class TestMergeViaRrf:
    def test_single_ranker_preserves_order(self):
        chunks = [_c("a"), _c("b"), _c("c")]
        result = _merge_via_rrf(
            rankings=(chunks,), rrf_constant=60, top_k=3
        )
        assert [r.content for r in result] == ["a", "b", "c"]

    def test_consensus_chunk_ranks_higher_than_disagreement(self):
        """A chunk present in both rankers (even at modest rank in
        each) should outrank chunks present in only one ranker —
        consensus is stronger signal than single-ranker top-1."""
        # Ranker A: a > b > c
        # Ranker B: c > d > e
        # c is in BOTH at ranks 3 and 1 → RRF score 1/63 + 1/61
        # a, b, d, e each only in one ranker
        ranker_a = [_c("a"), _c("b"), _c("c")]
        ranker_b = [_c("c"), _c("d"), _c("e")]

        result = _merge_via_rrf(
            rankings=(ranker_a, ranker_b), rrf_constant=60, top_k=5
        )

        # "c" must be ranked #1 because it accumulated two RRF terms.
        assert result[0].content == "c"

    def test_top_k_caps_result_size(self):
        ranker = [_c(letter) for letter in "abcdefghij"]
        result = _merge_via_rrf(
            rankings=(ranker,), rrf_constant=60, top_k=3
        )
        assert len(result) == 3

    def test_fused_score_is_stamped_on_returned_chunks(self):
        """Callers that inspect ``.score`` should see the merged RRF
        value, not the original cosine / ts_rank_cd score."""
        ranker_a = [_c("only_a", score=0.99)]
        ranker_b = [_c("only_b", score=0.99)]

        result = _merge_via_rrf(
            rankings=(ranker_a, ranker_b), rrf_constant=60, top_k=2
        )

        for chunk in result:
            # The RRF score for a single rank-1 appearance is
            # 1 / (60 + 1) ≈ 0.0164 — definitely not the original 0.99.
            assert chunk.score < 0.5

    def test_rrf_constant_affects_score_curve(self):
        """Larger ``rrf_constant`` flattens the rank curve, which
        reduces the gap between ranks.  We assert the contract
        (higher constant → smaller top-1 score) without coupling to
        a specific numeric value."""
        ranker = [_c("a")]

        low = _merge_via_rrf(
            rankings=(ranker,), rrf_constant=10, top_k=1
        )
        high = _merge_via_rrf(
            rankings=(ranker,), rrf_constant=1000, top_k=1
        )

        assert low[0].score > high[0].score


class TestHybridSearchRrfFallbacks:
    def _stub_embeddings(self):
        return patch(
            "components.knowledge.infrastructure.factories.embeddings."
            "factory.EmbeddingsFactory.create_embeddings",
            return_value=MagicMock(
                embed_query=lambda q: [0.1, 0.2, 0.3]
            ),
        )

    def test_keyword_empty_returns_pure_vector(self):
        vector_results = [_c("v1"), _c("v2"), _c("v3")]
        adapter = PgVectorStoreAdapter()
        with self._stub_embeddings(), patch.object(
            adapter, "_vector_search", return_value=vector_results
        ), patch.object(
            adapter, "_keyword_search", return_value=[]
        ):
            result = adapter.hybrid_search_rrf("query", k=2)

        assert [r.content for r in result] == ["v1", "v2"]

    def test_keyword_error_returns_pure_vector(self):
        vector_results = [_c("v1"), _c("v2")]
        adapter = PgVectorStoreAdapter()
        with self._stub_embeddings(), patch.object(
            adapter, "_vector_search", return_value=vector_results
        ), patch.object(
            adapter,
            "_keyword_search",
            side_effect=RuntimeError("tsquery syntax error"),
        ):
            result = adapter.hybrid_search_rrf("query", k=2)

        assert [r.content for r in result] == ["v1", "v2"]

    def test_embedding_failure_falls_back_to_keyword_only(self):
        keyword_results = [_c("k1"), _c("k2"), _c("k3")]
        adapter = PgVectorStoreAdapter()
        with patch(
            "components.knowledge.infrastructure.factories.embeddings."
            "factory.EmbeddingsFactory.create_embeddings",
            side_effect=RuntimeError("OpenAI down"),
        ), patch.object(
            adapter, "_keyword_search", return_value=keyword_results
        ):
            result = adapter.hybrid_search_rrf("query", k=2)

        assert [r.content for r in result] == ["k1", "k2"]


class TestHybridSearchRrfMergesWhenBothRankersReturn:
    def _stub_embeddings(self):
        return patch(
            "components.knowledge.infrastructure.factories.embeddings."
            "factory.EmbeddingsFactory.create_embeddings",
            return_value=MagicMock(
                embed_query=lambda q: [0.1, 0.2, 0.3]
            ),
        )

    def test_consensus_chunk_surfaces_to_the_top(self):
        # Vector ranks: a > b > consensus
        # Keyword ranks: consensus > d > e
        # consensus is in both — RRF should put it first.
        vector_results = [_c("a"), _c("b"), _c("consensus")]
        keyword_results = [_c("consensus"), _c("d"), _c("e")]
        adapter = PgVectorStoreAdapter()
        with self._stub_embeddings(), patch.object(
            adapter, "_vector_search", return_value=vector_results
        ), patch.object(
            adapter, "_keyword_search", return_value=keyword_results
        ):
            result = adapter.hybrid_search_rrf("query", k=3)

        assert result[0].content == "consensus"

    def test_returns_at_most_top_k(self):
        vector_results = [_c(f"v{i}") for i in range(10)]
        keyword_results = [_c(f"k{i}") for i in range(10)]
        adapter = PgVectorStoreAdapter()
        with self._stub_embeddings(), patch.object(
            adapter, "_vector_search", return_value=vector_results
        ), patch.object(
            adapter, "_keyword_search", return_value=keyword_results
        ):
            result = adapter.hybrid_search_rrf("query", k=3)

        assert len(result) == 3
