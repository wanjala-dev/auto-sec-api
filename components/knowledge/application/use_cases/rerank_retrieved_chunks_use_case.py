"""Tier 3 #10 — re-score retrieved chunks with a cross-encoder.

Pure cosine top-k from pgvector ranks chunks by embedding similarity,
which works well for semantic recall but can let weakly-relevant
chunks slip ahead of the actually-best match.  A cross-encoder
reranker re-scores each retrieved chunk against the *original* query
in a single forward pass, surfacing the most relevant ones to the
top-k that the LLM actually sees.

The pipeline both callers use:

    chunks = vector_store.search(query, k=20)        # over-fetch
    top    = rerank(query, chunks, top_k=5)          # this use case
    pass `top` to the planner / agent

Singleton reranker — the sentence-transformers cross-encoder model
takes ~80MB and ~0.5s to load.  Loading it on every retrieval would
double per-call latency.  Cached on first use; subsequent calls are
just the forward pass (~10ms on a 20-chunk batch on CPU).

Failure modes are silent: any reranker error returns the input
chunks truncated to ``top_k`` (i.e., the original cosine order).
Retrieval must never crash because reranking did.

Precision tuning via ``min_score`` (2026-06-10):
    The first RAG eval baseline showed Context Precision = 0.41
    aggregate (0.22 for transactional + ambiguous categories).
    Root cause: the reranker scored every candidate and returned
    the top-N regardless of how low the scores were.  A chunk
    barely related to the query still made the top-N if no better
    chunk existed in the candidate set, dragging precision down.

    ``min_score`` drops chunks below the configured threshold
    BEFORE truncating to ``top_k``.  Trades recall for precision —
    when no chunk clears the threshold, the planner gets fewer
    chunks (or zero) but the chunks it does get are higher
    quality.

    Default 0.0 → no filtering (current behavior, baseline match).
    Set ``KNOWLEDGE_RERANK_MIN_SCORE`` env var to apply a
    threshold globally; the deep-planner prefetch reads it.
    Cross-encoder scores are model-specific — measure with the
    eval harness before flipping the prod default.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 3 #10 and the
baseline-driven follow-up in ``docs/plans/RAG_EVAL_BASELINE.md``.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from components.knowledge.application.ports.reranker_port import RerankerPort
from components.knowledge.application.ports.vector_store_port import RetrievedChunk

logger = logging.getLogger(__name__)

# The over-fetch multiplier.  Top-k requested = 5 means we ask pgvector
# for 20 and let the reranker pick the best 5.  Larger candidate sets
# give the reranker more to work with but cost embedding bandwidth.
DEFAULT_FETCH_MULTIPLIER = 4

# Sentinel for "no filtering" — used as the ``min_score`` default
# and as the env-var-unset return value.  Replaced the previous
# ``DEFAULT_MIN_SCORE = 0.0`` after the 2026-06-11 threshold A/B
# (task #84) showed cross-encoder logits skew negative, so ``0.0``
# is a real (aggressive) threshold and cannot double as "no filter".
DEFAULT_MIN_SCORE: Optional[float] = None

# Module-level singleton — instantiated on first ``rerank()`` call so
# the model is only loaded once per worker process.  Reset to None to
# force re-instantiation (used by tests).
_CACHED_RERANKER: Optional[RerankerPort] = None
_CACHED_RERANKER_LOAD_FAILED: bool = False


def reset_cached_reranker_for_tests() -> None:
    """Test-only — clear the cached reranker so the next call re-loads.

    Production code never calls this.
    """
    global _CACHED_RERANKER, _CACHED_RERANKER_LOAD_FAILED
    _CACHED_RERANKER = None
    _CACHED_RERANKER_LOAD_FAILED = False


def _get_reranker() -> Optional[RerankerPort]:
    """Return the cached reranker port, or None if loading failed.

    A previous failure short-circuits all subsequent attempts so a
    missing sentence-transformers install doesn't pay the
    import-attempt cost on every retrieval call.
    """
    global _CACHED_RERANKER, _CACHED_RERANKER_LOAD_FAILED
    if _CACHED_RERANKER is not None:
        return _CACHED_RERANKER
    if _CACHED_RERANKER_LOAD_FAILED:
        return None
    try:
        from components.knowledge.application.providers.ai_reranker_provider import (
            AIRerankerProvider,
        )

        _CACHED_RERANKER = AIRerankerProvider().get_port()
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "knowledge: failed to instantiate reranker, falling back "
            "to cosine-only retrieval",
            exc_info=True,
        )
        _CACHED_RERANKER_LOAD_FAILED = True
        return None
    return _CACHED_RERANKER


class RerankRetrievedChunksUseCase:
    """Re-score retrieved chunks against the original query."""

    def rerank(
        self,
        *,
        query: str,
        chunks: List[RetrievedChunk],
        top_k: int = 5,
        min_score: Optional[float] = DEFAULT_MIN_SCORE,
    ) -> List[RetrievedChunk]:
        """Return the best *top_k* chunks for *query*.

        Empty or single-chunk inputs are returned unchanged (no point
        running a reranker on nothing).  Failure to load or call the
        reranker returns ``chunks[:top_k]`` — original cosine order.

        ``min_score`` is the precision knob.  Chunks whose reranker
        score is below this threshold are dropped before truncating
        to ``top_k``.  A query with no chunks clearing the threshold
        gets an empty list — the planner then runs without
        grounding, which is correct: low-relevance chunks are worse
        than no chunks because they make the LLM confabulate from
        noise.

        ``None`` (default) means "no filter" — every chunk the
        reranker returns is eligible for the top-k.  Any float
        (positive OR negative) applies the threshold.  Negative
        values are useful when the reranker model's score
        distribution skews negative (e.g. cross-encoder MS-MARCO
        on our workspace-snapshot corpus, mean -7.6) — a threshold
        like ``-3.0`` drops only the truly irrelevant tail
        without collapsing recall.
        """
        if not chunks:
            return []
        if top_k <= 0:
            return []
        if len(chunks) <= 1:
            # Single-chunk path still needs to respect min_score so
            # callers that opt in get the same filtering guarantee
            # they expect for multi-chunk inputs.
            if min_score is not None and chunks[0].score < min_score:
                return []
            return chunks[:top_k]

        reranker = _get_reranker()
        if reranker is None:
            return chunks[:top_k]

        try:
            # Ask the reranker for every chunk re-scored, so we can
            # filter on the new scores BEFORE truncating to top_k.
            # Passing top_k=top_k here would cut off candidates the
            # threshold could have kept.
            reranked = reranker.rerank(
                query=query, chunks=chunks, top_k=len(chunks)
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "knowledge: reranker call failed, falling back to "
                "cosine-only order",
                exc_info=True,
            )
            return chunks[:top_k]

        if not reranked:
            return chunks[:top_k]

        if min_score is not None:
            filtered = [c for c in reranked if c.score >= min_score]
            return filtered[:top_k]
        return reranked[:top_k]
