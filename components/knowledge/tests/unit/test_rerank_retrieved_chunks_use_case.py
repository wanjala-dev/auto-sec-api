"""Tier 3 #10 — unit tests for the chunk reranker use case.

The reranker port is stubbed; we verify the contract:

* Empty / single-chunk / zero-k inputs pass through (no point
  reranking nothing).
* When the reranker is available, the use case calls ``.rerank()``
  with the original query and returns its result truncated to
  ``top_k``.
* When the reranker fails to load, returns ``chunks[:top_k]`` in
  original cosine order.
* When the loaded reranker errors mid-call, same fallback.
* Subsequent calls hit the module-level singleton (no re-init).
* The reset helper lets tests force re-instantiation.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #10.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from components.knowledge.application.ports.vector_store_port import RetrievedChunk
from components.knowledge.application.use_cases.rerank_retrieved_chunks_use_case import (
    DEFAULT_FETCH_MULTIPLIER,
    RerankRetrievedChunksUseCase,
    reset_cached_reranker_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton_between_tests():
    """Each test starts with a fresh singleton cache."""
    reset_cached_reranker_for_tests()
    yield
    reset_cached_reranker_for_tests()


def _chunk(content: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(content=content, metadata={}, score=score)


class TestPassThroughCases:
    def test_empty_chunks_returns_empty_list(self):
        use_case = RerankRetrievedChunksUseCase()
        assert use_case.rerank(query="x", chunks=[], top_k=5) == []

    def test_zero_top_k_returns_empty_list(self):
        use_case = RerankRetrievedChunksUseCase()
        assert (
            use_case.rerank(query="x", chunks=[_chunk("a", 0.9)], top_k=0)
            == []
        )

    def test_single_chunk_is_returned_unchanged(self):
        use_case = RerankRetrievedChunksUseCase()
        chunks = [_chunk("only one", 0.9)]
        assert use_case.rerank(query="x", chunks=chunks, top_k=5) == chunks


class TestRerankHappyPath:
    def test_calls_reranker_with_original_query(self):
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
        # Reranker returns chunks in REVERSE order — proves we're
        # surfacing reranker output, not raw cosine order.
        reversed_chunks = list(reversed(chunks))
        fake = MagicMock()
        fake.rerank.return_value = reversed_chunks
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="user goal", chunks=chunks, top_k=2
            )

        # We ask the reranker for ALL chunks scored (not just top_k)
        # so the use case can apply min_score filtering before
        # truncating. See the use case docstring for the rationale.
        fake.rerank.assert_called_once_with(
            query="user goal", chunks=chunks, top_k=len(chunks)
        )
        assert result == reversed_chunks[:2]

    def test_singletons_the_reranker_across_invocations(self):
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        fake = MagicMock()
        fake.rerank.return_value = chunks
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ) as mock_get_port:
            use_case = RerankRetrievedChunksUseCase()
            use_case.rerank(query="x", chunks=chunks, top_k=2)
            use_case.rerank(query="y", chunks=chunks, top_k=2)
            use_case.rerank(query="z", chunks=chunks, top_k=2)

        # Reranker should be constructed ONCE across all three calls.
        assert mock_get_port.call_count == 1
        assert fake.rerank.call_count == 3

    def test_default_fetch_multiplier_is_four(self):
        """Document the over-fetch constant — callers ask vectorstore
        for ``top_k * multiplier`` candidates before reranking."""
        assert DEFAULT_FETCH_MULTIPLIER == 4


class TestFallbackBehavior:
    def test_returns_cosine_top_k_when_reranker_load_fails(self):
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.__init__",
            side_effect=RuntimeError("provider boot failed"),
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=2
            )

        assert result == chunks[:2], (
            "When the reranker can't load, fall back to the original "
            "cosine order truncated to top_k."
        )

    def test_returns_cosine_top_k_when_reranker_call_raises(self):
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
        fake = MagicMock()
        fake.rerank.side_effect = RuntimeError("model crashed")
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=2
            )

        assert result == chunks[:2]

    def test_returns_cosine_top_k_when_reranker_returns_empty(self):
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        fake = MagicMock()
        fake.rerank.return_value = []
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=2
            )

        assert result == chunks[:2]

    def test_failed_load_short_circuits_subsequent_calls(self):
        """Once we know the reranker won't load, every retrieval call
        must skip the import attempt — no per-call cost."""
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.__init__",
            side_effect=RuntimeError("missing"),
        ) as mock_init:
            use_case = RerankRetrievedChunksUseCase()
            use_case.rerank(query="x", chunks=chunks, top_k=2)
            use_case.rerank(query="x", chunks=chunks, top_k=2)
            use_case.rerank(query="x", chunks=chunks, top_k=2)

        # First call attempts to construct; subsequent calls
        # short-circuit on the cached failure flag.
        assert mock_init.call_count == 1


class TestMinScoreThreshold:
    """Precision tuning knob from the 2026-06-10 RAG eval baseline.

    Baseline showed Context Precision = 0.41 — chunks barely related
    to the query were making the top-N because no better chunks
    existed in the candidate set. ``min_score`` drops chunks below
    the threshold BEFORE truncating to top_k.
    """

    def test_keeps_chunks_at_or_above_threshold(self):
        """Score == threshold passes; score > threshold passes."""
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        # Reranker re-scores: a=2.0, b=1.5
        scored = [_chunk("a", 2.0), _chunk("b", 1.5)]
        fake = MagicMock()
        fake.rerank.return_value = scored
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=5, min_score=1.5
            )
        assert [c.content for c in result] == ["a", "b"]

    def test_drops_chunks_below_threshold(self):
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
        scored = [_chunk("a", 3.0), _chunk("b", 1.0), _chunk("c", 0.2)]
        fake = MagicMock()
        fake.rerank.return_value = scored
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=5, min_score=1.0
            )
        # 'c' falls below threshold and is dropped — even though
        # there's still room within top_k. The planner gets a
        # higher-quality (but smaller) chunk set.
        assert [c.content for c in result] == ["a", "b"]

    def test_no_chunks_clear_threshold_returns_empty(self):
        """When every chunk scores below the threshold, the planner
        runs WITHOUT grounding. This is intentional: noisy chunks
        make the LLM confabulate; no chunks at least gives the
        planner an honest 'no relevant context' signal.
        """
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        scored = [_chunk("a", 0.3), _chunk("b", 0.1)]
        fake = MagicMock()
        fake.rerank.return_value = scored
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=5, min_score=1.0
            )
        assert result == []

    def test_default_min_score_is_none_so_existing_callers_unchanged(self):
        """Callers that don't pass min_score must see the same behavior
        as before the parameter existed — no chunks filtered out.
        Default is now ``None`` (the no-filter sentinel) — task #84
        changed this from ``0.0`` because cross-encoder logits skew
        negative, so 0.0 is a real threshold not a no-op.
        """
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        # Reranker scores everything below 0 — under the old
        # ``min_score=0.0 = no filter`` contract these would still
        # come through.  They must still come through with the new
        # ``min_score=None = no filter`` contract.
        scored = [_chunk("a", -0.5), _chunk("b", -2.0)]
        fake = MagicMock()
        fake.rerank.return_value = scored
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            # No min_score passed.
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=5
            )
        # Both kept — default None means no filtering.
        assert [c.content for c in result] == ["a", "b"]

    def test_explicit_zero_threshold_drops_negatives(self):
        """0.0 is now a real (aggressive) threshold for cross-encoder
        logits — distinguish it from None.  A chunk with score -0.5
        gets dropped at min_score=0.0; under the previous contract
        it would have been kept because 0.0 was the no-filter
        sentinel.
        """
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8)]
        scored = [_chunk("a", 0.001), _chunk("b", -0.5)]
        fake = MagicMock()
        fake.rerank.return_value = scored
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=5, min_score=0.0
            )
        assert [c.content for c in result] == ["a"]

    def test_negative_threshold_drops_only_irrelevant_tail(self):
        """Negative threshold is the point of task #84.  Cross-encoder
        logits skew negative on our corpus; min_score=-3.0 should
        keep marginal chunks (score -2.0) while dropping clearly
        irrelevant ones (score -10.0).
        """
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
        scored = [_chunk("a", -1.0), _chunk("b", -2.0), _chunk("c", -10.0)]
        fake = MagicMock()
        fake.rerank.return_value = scored
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=5, min_score=-3.0
            )
        # 'a' and 'b' kept (scores >= -3.0); 'c' dropped.
        assert [c.content for c in result] == ["a", "b"]

    def test_single_chunk_path_respects_threshold(self):
        """The single-chunk fast path must honor min_score, otherwise
        a caller would get a chunk that fails their threshold
        depending on input size."""
        chunks = [_chunk("only", 0.05)]
        result_below = RerankRetrievedChunksUseCase().rerank(
            query="x", chunks=chunks, top_k=5, min_score=0.5
        )
        assert result_below == []

        chunks = [_chunk("only", 0.9)]
        result_above = RerankRetrievedChunksUseCase().rerank(
            query="x", chunks=chunks, top_k=5, min_score=0.5
        )
        assert result_above == chunks

    def test_truncates_to_top_k_after_filtering(self):
        """Filtering happens BEFORE the top_k truncation, so a
        threshold of 0 with top_k=2 still returns 2 chunks even if
        all 3 candidates have low scores."""
        chunks = [_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)]
        scored = [_chunk("a", 3.0), _chunk("b", 2.0), _chunk("c", 1.5)]
        fake = MagicMock()
        fake.rerank.return_value = scored
        with patch(
            "components.knowledge.application.providers."
            "ai_reranker_provider.AIRerankerProvider.get_port",
            return_value=fake,
        ):
            result = RerankRetrievedChunksUseCase().rerank(
                query="x", chunks=chunks, top_k=2, min_score=1.0
            )
        # All three clear the threshold but top_k caps at 2.
        assert [c.content for c in result] == ["a", "b"]
