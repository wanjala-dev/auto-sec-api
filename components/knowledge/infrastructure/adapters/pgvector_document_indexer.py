"""Store uploaded-document chunks into the canonical ``EmbeddingChunk`` store.

Why this exists (2026-07-15 store-split fix):

The PDF/document embed paths (``pdf_embeddings.create_embeddings_for_pdf`` and
``document_embeddings.create_embeddings_for_document``) historically wrote their
chunks through ``VectorStoreFactory`` → LangChain ``PGVector``, which manages
its OWN tables (``langchain_pg_collection`` / ``langchain_pg_embedding``).

But the agent retrieval stack reads a DIFFERENT store: ``PdfChatUseCase`` (and
every agent's ``retrieve_workspace_context``) resolves its vector store through
``AIVectorStoreProvider().get_port()`` → ``PgvectorStoreAdapter``, which queries
the Django ``EmbeddingChunk`` model (table ``ai_embedding_chunks``). The
workspace snapshot indexer writes ``EmbeddingChunk`` too — so workspace RAG
worked, but an uploaded PDF (written to ``langchain_pg_embedding``) was invisible
to ``has_indexed_content`` and search. Result: every PDF/document chat returned
"No content found for this document" (HTTP 404 ``PdfChatNoContent``) even though
the embed job succeeded.

This helper closes the split by writing uploaded-document chunks into the SAME
``EmbeddingChunk`` store retrieval reads, using the exact embed → bulk_create →
raw-``vector``-column write pattern the workspace indexer uses
(``PgVectorWorkspaceIndexAdapter._replace_chunks`` / ``._attach_vectors``).

Non-pgvector deployments (a dev box running ``VECTOR_STORE_PROVIDER=elasticsearch``)
keep the factory write path, because on those the retrieval port resolves to the
matching Elasticsearch adapter — so write and read stay aligned there too.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.conf import settings
from django.db import connection, transaction

logger = logging.getLogger(__name__)


def index_documents(documents, *, embeddings_provider: str = "openai") -> int:
    """Embed ``documents`` and store them where agent retrieval reads.

    ``documents`` are LangChain ``Document`` objects carrying ``page_content``
    and a ``metadata`` dict (must include ``pdf_id`` + ``workspace_id`` +
    ``user_id`` so ``PdfChatUseCase`` filters match). Returns the chunk count.
    """
    provider = getattr(settings, "VECTOR_STORE_PROVIDER", "pgvector")
    if provider != "pgvector":
        return _index_via_factory(documents, embeddings_provider)
    return _index_pgvector(documents, embeddings_provider)


def _index_via_factory(documents, embeddings_provider: str) -> int:
    """Legacy path for non-pgvector deployments (retrieval uses the same store)."""
    from components.knowledge.infrastructure.factories.embeddings.factory import (
        EmbeddingsFactory,
    )
    from components.knowledge.infrastructure.factories.vector_stores.factory import (
        VectorStoreFactory,
    )

    vector_store = VectorStoreFactory.create_vector_store(
        embeddings_instance=EmbeddingsFactory.create_embeddings(provider=embeddings_provider),
    )
    vector_store.add_documents(list(documents))
    return len(list(documents))


def _index_pgvector(documents, embeddings_provider: str) -> int:
    from components.knowledge.infrastructure.factories.embeddings.factory import (
        EmbeddingsFactory,
    )
    from infrastructure.persistence.ai.models import EmbeddingChunk

    documents = list(documents)
    texts = [doc.page_content for doc in documents]
    if not texts:
        return 0

    embeddings_client = EmbeddingsFactory.create_embeddings(provider=embeddings_provider)
    vectors: list[list[float]] = embeddings_client.embed_documents(texts)
    if len(vectors) != len(documents):
        raise RuntimeError(f"embedding count mismatch: got {len(vectors)} vectors for {len(documents)} chunks")

    with transaction.atomic():
        rows = [EmbeddingChunk(content=doc.page_content, metadata=dict(doc.metadata or {})) for doc in documents]
        created = EmbeddingChunk.objects.bulk_create(rows)
        _attach_vectors(created, vectors)

    logger.info("pgvector_document_indexer stored %s EmbeddingChunk rows", len(created))
    return len(created)


def _attach_vectors(created_rows: Iterable, vectors: list[list[float]]) -> None:
    """Write the raw pgvector ``embedding`` column (Django can't bind ``vector``).

    Mirrors ``PgVectorWorkspaceIndexAdapter._attach_vectors`` — guarded by a
    pgvector-availability probe so the writer stays usable on the SQLite/no-vector
    test DB (chunks are written without embeddings; retrieval is inert there but
    ``has_indexed_content`` — which reads ``metadata`` only — still passes).
    """
    if not _pgvector_available(connection):
        logger.debug(
            "Skipping pgvector embedding write: vector type unavailable on %s",
            connection.vendor,
        )
        return

    with connection.cursor() as cursor:
        for row, vector in zip(created_rows, vectors):
            cursor.execute(
                "UPDATE ai_embedding_chunks SET embedding = %s::vector WHERE id = %s",
                [str(list(vector)), str(row.id)],
            )


def _pgvector_available(conn) -> bool:
    if conn.vendor != "postgresql":
        return False
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")
        return cursor.fetchone() is not None
