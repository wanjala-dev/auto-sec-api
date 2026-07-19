"""Port for vector-store backends — domain stays SDK-free.

Adapters wrap Elasticsearch, Pinecone, ChromaDB, pgvector, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class SearchMode(StrEnum):
    """How the vector store should combine retrieval signals."""

    VECTOR = "vector"       # Pure semantic similarity (default)
    KEYWORD = "keyword"     # Pure BM25 / keyword match
    HYBRID = "hybrid"       # Weighted combination of vector + keyword


@dataclass(frozen=True)
class RetrievedChunk:
    """Normalised search result returned by any vector-store adapter."""

    content: str
    metadata: dict = field(default_factory=dict)
    score: float = 0.0


class VectorStorePort(ABC):
    """Abstract contract every vector-store adapter must satisfy."""

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top-*k* chunks matching *query*."""
        ...

    def hybrid_search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
        mode: SearchMode = SearchMode.HYBRID,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[RetrievedChunk]:
        """Return top-*k* chunks using hybrid BM25 + vector retrieval.

        Default implementation falls back to plain ``search`` — adapters
        that support native hybrid (e.g. Elasticsearch RRF) should
        override this for better quality.

        ``vector_weight`` and ``keyword_weight`` control the relative
        importance of each signal (must sum to 1.0).
        """
        return self.search(query, k=k, filters=filters)

    def scoped_search(
        self,
        query: str,
        *,
        k: int = 5,
        agent_type: str | None = None,
        workspace_id: str | None = None,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        """Search scoped to a specific agent type's knowledge base.

        Adds ``agent_type`` and ``workspace_id`` to the filter set so
        each agent retrieves only from its own indexed content rather
        than the shared store.

        Default implementation merges scope into filters and delegates
        to ``search``.  Adapters may override for native namespace support.
        """
        scoped_filters = dict(filters or {})
        if agent_type:
            scoped_filters["agent_type"] = agent_type
        if workspace_id:
            scoped_filters["workspace_id"] = workspace_id
        return self.search(query, k=k, filters=scoped_filters)

    @abstractmethod
    def has_indexed_content(
        self,
        *,
        pdf_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Return True if indexed chunks exist for the given scope."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return a stable slug identifying this backend (e.g. 'elasticsearch')."""
        ...
