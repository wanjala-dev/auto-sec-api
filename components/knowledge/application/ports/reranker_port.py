"""Port for cross-encoder reranking — domain stays SDK-free.

After initial retrieval (vector, keyword, or hybrid), a reranker
re-scores each chunk against the original query using a cross-encoder
model, producing higher-quality top-k results.

Adapters wrap Cohere Rerank, sentence-transformers cross-encoders,
Jina Reranker, or any scoring API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.knowledge.application.ports.vector_store_port import RetrievedChunk


class RerankerPort(ABC):
    """Abstract contract every reranker adapter must satisfy."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Re-score *chunks* against *query* and return the best *top_k*.

        When *top_k* is ``None``, return all chunks re-sorted by relevance.
        """
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return a stable slug (e.g. 'cohere', 'cross-encoder')."""
        ...
