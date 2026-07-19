"""Reranker adapter using sentence-transformers cross-encoder models.

Falls back to a simple keyword-overlap heuristic when the
``sentence-transformers`` package is not installed, so the system
degrades gracefully in environments without GPU or the dependency.
"""

from __future__ import annotations

import logging
import os

from components.knowledge.application.ports.reranker_port import RerankerPort
from components.knowledge.application.ports.vector_store_port import RetrievedChunk

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get(
    "RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)


class CrossEncoderRerankerAdapter(RerankerPort):
    """Cross-encoder reranker backed by ``sentence-transformers``.

    If the library is unavailable, uses a lightweight keyword-overlap
    heuristic so callers never need a hard dependency.
    """

    def __init__(self, *, model_name: str | None = None) -> None:
        self._model_name = model_name or _DEFAULT_MODEL
        self._cross_encoder = None
        self._fallback = False

        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]

            self._cross_encoder = CrossEncoder(self._model_name)
        except ImportError:
            logger.info(
                "sentence-transformers not installed — reranker will use "
                "keyword-overlap fallback"
            )
            self._fallback = True
        except Exception:
            logger.exception("Failed to load cross-encoder model %s", self._model_name)
            self._fallback = True

    # ── RerankerPort implementation ──────────────────────────────────

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        if self._fallback:
            scored = self._keyword_overlap_score(query, chunks)
        else:
            scored = self._cross_encode(query, chunks)

        scored.sort(key=lambda pair: pair[1], reverse=True)
        limit = top_k if top_k is not None else len(scored)
        return [
            RetrievedChunk(
                content=chunk.content,
                metadata=chunk.metadata,
                score=score,
            )
            for chunk, score in scored[:limit]
        ]

    def provider_name(self) -> str:
        if self._fallback:
            return "keyword-overlap-fallback"
        return f"cross-encoder:{self._model_name}"

    # ── Scoring strategies ───────────────────────────────────────────

    def _cross_encode(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[tuple[RetrievedChunk, float]]:
        pairs = [(query, chunk.content) for chunk in chunks]
        scores = self._cross_encoder.predict(pairs)  # type: ignore[union-attr]
        return list(zip(chunks, [float(s) for s in scores]))

    def _keyword_overlap_score(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> list[tuple[RetrievedChunk, float]]:
        """Simple Jaccard-like overlap as a zero-dependency fallback."""
        query_tokens = set(query.lower().split())
        results: list[tuple[RetrievedChunk, float]] = []
        for chunk in chunks:
            chunk_tokens = set(chunk.content.lower().split())
            if not query_tokens:
                results.append((chunk, chunk.score))
                continue
            overlap = len(query_tokens & chunk_tokens)
            score = overlap / max(len(query_tokens | chunk_tokens), 1)
            results.append((chunk, score))
        return results
