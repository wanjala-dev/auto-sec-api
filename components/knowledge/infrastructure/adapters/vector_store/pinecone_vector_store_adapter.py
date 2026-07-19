"""Pinecone vector-store adapter — wraps the Pinecone SDK behind VectorStorePort.

Requires ``pinecone-client`` (v3+).  Install with::

    pip install pinecone-client
"""

from __future__ import annotations

import logging
import os
from typing import Any

from components.knowledge.application.ports.vector_store_port import RetrievedChunk, VectorStorePort

logger = logging.getLogger(__name__)


class PineconeVectorStoreAdapter(VectorStorePort):
    """Adapter that delegates to a Pinecone index for vector similarity search."""

    def __init__(
        self,
        *,
        index_name: str | None = None,
        api_key: str | None = None,
        environment: str | None = None,
        namespace: str = "",
        embeddings_provider: str = "openai",
        embeddings_model: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._index_name = index_name or os.environ.get("PINECONE_INDEX", "default")
        self._api_key = api_key or os.environ.get("PINECONE_API_KEY", "")
        self._environment = environment or os.environ.get("PINECONE_ENVIRONMENT", "")
        self._namespace = namespace
        self._embeddings_provider = embeddings_provider
        self._embeddings_model = embeddings_model
        self._index: Any = None

    def _get_index(self) -> Any:
        """Lazily initialise the Pinecone index handle."""
        if self._index is None:
            from pinecone import Pinecone  # type: ignore[import-untyped]

            pc = Pinecone(api_key=self._api_key)
            self._index = pc.Index(self._index_name)
        return self._index

    def _embed(self, text: str) -> list[float]:
        """Produce an embedding vector via the configured embeddings provider."""
        from components.knowledge.application.providers.ai_embeddings_provider import (
            AIEmbeddingsProvider,
        )

        port = AIEmbeddingsProvider().get_port(
            self._embeddings_provider,
            **({"model": self._embeddings_model} if self._embeddings_model else {}),
        )
        return port.embed_text(text)

    # ── VectorStorePort implementation ────────────────────────────────

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        index = self._get_index()
        vector = self._embed(query)

        # Build Pinecone metadata filter from the standard filters dict.
        pinecone_filter: dict | None = None
        if filters:
            pinecone_filter = {
                key: {"$eq": value}
                for key, value in filters.items()
                if value is not None
            } or None

        results = index.query(
            vector=vector,
            top_k=k,
            namespace=self._namespace,
            filter=pinecone_filter,
            include_metadata=True,
        )

        chunks: list[RetrievedChunk] = []
        for match in getattr(results, "matches", []):
            metadata = dict(getattr(match, "metadata", {}) or {})
            content = metadata.pop("text", "") or metadata.pop("content", "")
            chunks.append(
                RetrievedChunk(
                    content=str(content),
                    metadata=metadata,
                    score=float(getattr(match, "score", 0.0)),
                )
            )
        return chunks

    def has_indexed_content(
        self,
        *,
        pdf_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        filters: dict = {}
        if pdf_id:
            filters["pdf_id"] = pdf_id
        if workspace_id:
            filters["workspace_id"] = workspace_id
        if user_id:
            filters["user_id"] = user_id

        return len(self.search("", k=1, filters=filters or None)) > 0

    def provider_name(self) -> str:
        return "pinecone"
