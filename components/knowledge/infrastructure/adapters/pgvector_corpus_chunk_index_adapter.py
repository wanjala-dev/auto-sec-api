"""pgvector adapter that indexes a single keyed chunk into ``ai_embedding_chunks``.

Implements :class:`CorpusChunkIndexPort` — the sanctioned write door to the
``knowledge`` store for records that other contexts want retrievable (the first
consumer is Remediation Memory's vetted-fix corpus, ADR 0012 P4). It mirrors the
embed + raw-SQL-vector-attach discipline of ``PgVectorWorkspaceIndexAdapter`` but
for a SINGLE keyed chunk rather than a workspace snapshot:

- **Idempotent by key.** ``document_key`` is stamped into the chunk metadata; a
  repeat ``index_chunk`` deletes the prior row for that key and inserts a fresh
  one, so re-embedding the same record updates in place (never duplicates).
- **Best-effort embedding.** The vector is written via raw SQL only when the
  pgvector extension is present (pytest skips migrations, so the extension is
  absent on the test DB). When embedding is unavailable the row is still written
  with its content + metadata — the record stays metadata/keyword-retrievable and
  a later re-index attaches the vector. A genuine store-write failure DOES raise.

Reuses knowledge's own embeddings stack (``EmbeddingsFactory``) — no second
vector store, no parallel embeddings pipeline.
"""

from __future__ import annotations

import logging

from components.knowledge.application.ports.corpus_chunk_index_port import (
    CorpusChunkIndexPort,
)

logger = logging.getLogger(__name__)


class PgVectorCorpusChunkIndexAdapter(CorpusChunkIndexPort):
    """Writes one keyed chunk into ``ai_embedding_chunks`` (pgvector store)."""

    def __init__(self, *, embeddings_provider: str = "openai") -> None:
        self._embeddings_provider = embeddings_provider

    def index_chunk(self, *, document_key: str, content: str, metadata: dict) -> int:
        from django.db import transaction

        from infrastructure.persistence.ai.models import EmbeddingChunk

        if not document_key:
            raise ValueError("document_key is required to index a corpus chunk.")
        if not content or not content.strip():
            return 0

        # Compute the vector best-effort BEFORE the write so a slow/absent
        # embeddings backend never holds a DB transaction open. A failure here
        # degrades to "row without vector" — the record is still written.
        vector = self._embed(content)

        chunk_metadata = {**metadata, "document_key": document_key}

        with transaction.atomic():
            EmbeddingChunk.objects.filter(metadata__document_key=document_key).delete()
            row = EmbeddingChunk.objects.create(content=content, metadata=chunk_metadata)
            if vector is not None:
                self._attach_vector(row_id=str(row.id), vector=vector)

        logger.info(
            "corpus_chunk_indexed document_key=%s chunk_type=%s embedded=%s",
            document_key,
            metadata.get("chunk_type"),
            vector is not None,
        )
        return 1

    def delete_by_key(self, *, document_key: str) -> int:
        from infrastructure.persistence.ai.models import EmbeddingChunk

        if not document_key:
            return 0
        deleted, _ = EmbeddingChunk.objects.filter(metadata__document_key=document_key).delete()
        logger.info("corpus_chunk_deleted document_key=%s chunks=%d", document_key, int(deleted))
        return int(deleted)

    # ── Internals ────────────────────────────────────────────────────

    def _embed(self, content: str) -> list[float] | None:
        """Return the embedding vector for *content*, or ``None`` if unavailable.

        Best-effort: any embeddings-backend failure (no API key, network, missing
        pgvector) degrades to ``None`` so indexing never fails the caller's flow.
        """
        if not self._pgvector_available():
            return None
        try:
            from components.knowledge.infrastructure.factories.embeddings.factory import (
                EmbeddingsFactory,
            )

            client = EmbeddingsFactory.create_embeddings(provider=self._embeddings_provider)
            return list(client.embed_query(content))
        except Exception:
            logger.exception("corpus_chunk_embed_failed (row written without vector)")
            return None

    @staticmethod
    def _attach_vector(*, row_id: str, vector: list[float]) -> None:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE ai_embedding_chunks SET embedding = %s::vector WHERE id = %s",
                [str(list(vector)), row_id],
            )

    @staticmethod
    def _pgvector_available() -> bool:
        from django.db import connection

        if connection.vendor != "postgresql":
            return False
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")
            return cursor.fetchone() is not None
