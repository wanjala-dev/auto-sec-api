"""FAISS vector-store adapter — wraps Meta FAISS behind VectorStorePort.

Requires ``faiss-cpu`` (or ``faiss-gpu``).  Install with::

    pip install faiss-cpu
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from components.knowledge.application.ports.vector_store_port import RetrievedChunk, VectorStorePort

logger = logging.getLogger(__name__)


class FAISSVectorStoreAdapter(VectorStorePort):
    """Adapter that delegates to a FAISS index for vector similarity search.

    Stores an in-memory FAISS index alongside a parallel metadata list.
    Optionally persists to disk (``persist_directory``).
    """

    def __init__(
        self,
        *,
        persist_directory: str | None = None,
        index_name: str = "default",
        embeddings_provider: str = "openai",
        embeddings_model: str | None = None,
        dimension: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._persist_directory = persist_directory or os.environ.get(
            "FAISS_PERSIST_DIR", "",
        )
        self._index_name = index_name
        self._embeddings_provider = embeddings_provider
        self._embeddings_model = embeddings_model
        self._dimension = dimension
        self._index: Any = None
        self._metadata_store: list[dict] = []
        self._documents: list[str] = []

    def _ensure_index(self) -> Any:
        """Lazily load or create the FAISS index."""
        if self._index is not None:
            return self._index

        import faiss  # type: ignore[import-untyped]
        import numpy as np  # noqa: F401 — used for array ops below

        index_path = self._index_file_path()

        if index_path and index_path.exists():
            self._index = faiss.read_index(str(index_path))
            meta_path = index_path.with_suffix(".meta.json")
            if meta_path.exists():
                data = json.loads(meta_path.read_text())
                self._metadata_store = data.get("metadata", [])
                self._documents = data.get("documents", [])
            logger.info("Loaded FAISS index from %s (%d vectors)", index_path, self._index.ntotal)
        else:
            dim = self._dimension or self._detect_dimension()
            self._index = faiss.IndexFlatL2(dim)
            logger.info("Created new FAISS IndexFlatL2 (dim=%d)", dim)

        return self._index

    def _detect_dimension(self) -> int:
        """Embed a probe string to discover the vector dimension."""
        probe = self._embed("dimension probe")
        return len(probe)

    def _index_file_path(self) -> Path | None:
        if not self._persist_directory:
            return None
        return Path(self._persist_directory) / f"{self._index_name}.faiss"

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
        import numpy as np

        index = self._ensure_index()
        if index.ntotal == 0:
            return []

        vector = np.array([self._embed(query)], dtype="float32")
        distances, indices = index.search(vector, min(k, index.ntotal))

        chunks: list[RetrievedChunk] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            metadata = self._metadata_store[idx] if idx < len(self._metadata_store) else {}
            content = self._documents[idx] if idx < len(self._documents) else ""

            # Apply filters
            if filters:
                skip = False
                for key, value in filters.items():
                    if value is not None and metadata.get(key) != value:
                        skip = True
                        break
                if skip:
                    continue

            chunks.append(
                RetrievedChunk(
                    content=str(content),
                    metadata=dict(metadata),
                    # FAISS returns L2 distance; convert to similarity.
                    score=max(1.0 / (1.0 + float(dist)), 0.0),
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
        return "faiss"
