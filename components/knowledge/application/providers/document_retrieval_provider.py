"""Composition root for the uploaded-documents retrieval port."""

from __future__ import annotations

from components.knowledge.application.ports.document_retrieval_port import (
    DocumentRetrievalPort,
)


def document_retrieval() -> DocumentRetrievalPort:
    """Return the default ``DocumentRetrievalPort`` (LangChain-PGVector-backed)."""
    from components.knowledge.infrastructure.adapters.pgvector_document_retrieval_adapter import (
        PgVectorDocumentRetrievalAdapter,
    )

    return PgVectorDocumentRetrievalAdapter()
