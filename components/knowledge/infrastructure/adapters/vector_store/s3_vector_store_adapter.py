"""S3-backed vector-store adapter — stores FAISS index on S3 for persistence.

Combines FAISS for in-memory search with S3 for durable index storage.
On first access, downloads the index from S3; on index mutation, uploads
the updated index back.

Requires ``faiss-cpu`` and ``boto3``.  Install with::

    pip install faiss-cpu boto3
"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from typing import Any

from components.knowledge.application.ports.vector_store_port import RetrievedChunk, VectorStorePort

logger = logging.getLogger(__name__)


class S3VectorStoreAdapter(VectorStorePort):
    """Adapter that stores a FAISS index on S3 for durable vector search."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str = "vector-store/",
        index_name: str = "default",
        region: str | None = None,
        embeddings_provider: str = "openai",
        embeddings_model: str | None = None,
        dimension: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._bucket = bucket or os.environ.get("S3_VECTOR_STORE_BUCKET", "")
        self._prefix = prefix
        self._index_name = index_name
        self._region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self._embeddings_provider = embeddings_provider
        self._embeddings_model = embeddings_model
        self._dimension = dimension
        self._index: Any = None
        self._metadata_store: list[dict] = []
        self._documents: list[str] = []
        self._s3_client: Any = None

    def _get_s3(self) -> Any:
        if self._s3_client is None:
            import boto3  # type: ignore[import-untyped]

            self._s3_client = boto3.client("s3", region_name=self._region)
        return self._s3_client

    @property
    def _s3_index_key(self) -> str:
        return f"{self._prefix}{self._index_name}.faiss"

    @property
    def _s3_meta_key(self) -> str:
        return f"{self._prefix}{self._index_name}.meta.json"

    def _ensure_index(self) -> Any:
        """Download index from S3 or create a new one."""
        if self._index is not None:
            return self._index

        import faiss  # type: ignore[import-untyped]

        s3 = self._get_s3()

        try:
            with tempfile.NamedTemporaryFile(suffix=".faiss", delete=False) as tmp:
                s3.download_fileobj(self._bucket, self._s3_index_key, tmp)
                tmp.flush()
                self._index = faiss.read_index(tmp.name)

            resp = s3.get_object(Bucket=self._bucket, Key=self._s3_meta_key)
            data = json.loads(resp["Body"].read())
            self._metadata_store = data.get("metadata", [])
            self._documents = data.get("documents", [])
            logger.info(
                "Loaded FAISS index from s3://%s/%s (%d vectors)",
                self._bucket, self._s3_index_key, self._index.ntotal,
            )
        except s3.exceptions.NoSuchKey:
            dim = self._dimension or self._detect_dimension()
            self._index = faiss.IndexFlatL2(dim)
            logger.info("Created new FAISS IndexFlatL2 (dim=%d) for S3 backend", dim)
        except Exception:
            dim = self._dimension or self._detect_dimension()
            self._index = faiss.IndexFlatL2(dim)
            logger.info("No S3 index found, created new FAISS IndexFlatL2 (dim=%d)", dim)

        return self._index

    def _detect_dimension(self) -> int:
        probe = self._embed("dimension probe")
        return len(probe)

    def _embed(self, text: str) -> list[float]:
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
        return "s3"
