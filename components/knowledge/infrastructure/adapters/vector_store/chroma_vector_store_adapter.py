"""ChromaDB vector-store adapter — wraps ChromaDB behind VectorStorePort.

Requires ``chromadb``.  Install with::

    pip install chromadb
"""

from __future__ import annotations

import logging
import os
from typing import Any

from components.knowledge.application.ports.vector_store_port import RetrievedChunk, VectorStorePort

logger = logging.getLogger(__name__)


class ChromaVectorStoreAdapter(VectorStorePort):
    """Adapter that delegates to a ChromaDB collection for vector similarity search."""

    def __init__(
        self,
        *,
        collection_name: str | None = None,
        persist_directory: str | None = None,
        host: str | None = None,
        port: int | None = None,
        embeddings_provider: str = "openai",
        embeddings_model: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._collection_name = collection_name or os.environ.get(
            "CHROMA_COLLECTION", "default",
        )
        self._persist_directory = persist_directory or os.environ.get(
            "CHROMA_PERSIST_DIR", "",
        )
        self._host = host or os.environ.get("CHROMA_HOST", "")
        self._port = port or int(os.environ.get("CHROMA_PORT", "8000"))
        self._embeddings_provider = embeddings_provider
        self._embeddings_model = embeddings_model
        self._collection: Any = None

    def _get_collection(self) -> Any:
        """Lazily initialise the Chroma collection handle."""
        if self._collection is None:
            import chromadb  # type: ignore[import-untyped]

            if self._host:
                client = chromadb.HttpClient(host=self._host, port=self._port)
            elif self._persist_directory:
                client = chromadb.PersistentClient(path=self._persist_directory)
            else:
                client = chromadb.Client()

            self._collection = client.get_or_create_collection(
                name=self._collection_name,
            )
        return self._collection

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
        collection = self._get_collection()
        query_embedding = self._embed(query)

        # Build Chroma where filter from the standard filters dict.
        where_filter: dict | None = None
        if filters:
            conditions = {
                key: value
                for key, value in filters.items()
                if value is not None
            }
            where_filter = conditions or None

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        chunks: list[RetrievedChunk] = []
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            chunks.append(
                RetrievedChunk(
                    content=str(doc or ""),
                    metadata=dict(meta or {}),
                    # Chroma returns distances; convert to similarity score.
                    score=max(1.0 - float(dist), 0.0),
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
        return "chroma"
