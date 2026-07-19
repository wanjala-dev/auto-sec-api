"""Tests for the cross-encoder reranker adapter.

The 2026-06-10 RAG eval baseline turned up that ``sentence-transformers``
was missing from the requirements file, so the adapter had been silently
running its Jaccard keyword-overlap fallback since Tier 3 #10 shipped.

These tests pin the contract so we don't silently regress into the
fallback again:

* When ``sentence-transformers`` is installed (the new prod state),
  the adapter loads the cross-encoder and ``provider_name`` reports
  the model slug — not the fallback marker.
* When the package is unavailable, the adapter still works (falls
  back to keyword-overlap) and ``provider_name`` reports the
  fallback marker, so an environment without the package fails
  loudly in the provider name rather than silently producing low
  precision scores.

See ``docs/plans/RAG_EVAL_BASELINE.md`` "cross-encoder reranker"
follow-up entries.
"""
from __future__ import annotations

import pytest

from components.knowledge.application.ports.vector_store_port import RetrievedChunk
from components.knowledge.infrastructure.adapters.reranker.cross_encoder_reranker_adapter import (
    CrossEncoderRerankerAdapter,
)


def _can_import_sentence_transformers() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _can_import_sentence_transformers(),
    reason="sentence-transformers not installed in this environment",
)
class TestCrossEncoderActuallyLoads:
    """Pin the contract that prod runs the real reranker.

    These tests skip in environments without ``sentence-transformers``
    so the suite doesn't fail in a stripped-down image, but they
    actively assert the cross-encoder is active anywhere the library
    is available — including local dev + prod.
    """

    def test_provider_name_is_cross_encoder_not_fallback(self):
        adapter = CrossEncoderRerankerAdapter()
        name = adapter.provider_name()
        assert name.startswith("cross-encoder:"), (
            "When sentence-transformers is installed, the adapter MUST "
            "load the cross-encoder and report it in provider_name. "
            "Getting 'keyword-overlap-fallback' here means the install "
            "regressed and Context Precision will silently drop — same "
            "failure mode as the 2026-06-10 baseline finding."
        )

    def test_cross_encoder_returns_scored_chunks(self):
        """End-to-end: real model produces real scores."""
        adapter = CrossEncoderRerankerAdapter()
        chunks = [
            RetrievedChunk(
                content="Zaylan is a literacy nonprofit in East Africa.",
                metadata={"section": "mission"},
                score=0.5,
            ),
            RetrievedChunk(
                content="The donation total last month was USD 435.",
                metadata={"section": "recent_activity"},
                score=0.5,
            ),
        ]
        result = adapter.rerank(
            query="What does Zaylan do?", chunks=chunks, top_k=2
        )
        assert len(result) == 2
        # The mission chunk should rank higher than the donation total
        # for "what does Zaylan do?" — proves the cross-encoder is
        # actually scoring semantically, not just returning input order.
        assert result[0].content.startswith("Zaylan is a literacy"), (
            f"Cross-encoder should rank the mission chunk first; "
            f"got order: {[c.content[:30] for c in result]}"
        )


class TestFallbackPath:
    """The keyword-overlap fallback must keep working as a safety net."""

    def test_provider_name_reports_fallback_when_forced(self, monkeypatch):
        """Force the fallback path by setting _fallback=True directly."""
        adapter = CrossEncoderRerankerAdapter()
        adapter._fallback = True
        adapter._cross_encoder = None
        assert adapter.provider_name() == "keyword-overlap-fallback"

    def test_fallback_path_returns_chunks_in_relevance_order(self):
        adapter = CrossEncoderRerankerAdapter()
        adapter._fallback = True
        adapter._cross_encoder = None
        chunks = [
            RetrievedChunk(content="apple banana cherry", metadata={}, score=0.5),
            RetrievedChunk(content="orange grape pear", metadata={}, score=0.5),
        ]
        # Jaccard overlap with the query "apple cherry" should rank
        # the first chunk higher.
        result = adapter.rerank(
            query="apple cherry", chunks=chunks, top_k=2
        )
        assert result[0].content == "apple banana cherry"
