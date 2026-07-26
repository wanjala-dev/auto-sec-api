"""Published seam (Open Host Service) for knowledge's document-indexing plumbing.

The knowledge context owns embedding + vector storage. The shared_platform
document-index ORCHESTRATION (``RequestDocumentIndexUseCase``, the upload tasks,
the diagnostics) legitimately drives indexing, but must not reach into knowledge
INFRASTRUCTURE to do it (cross-context infrastructure imports are forbidden; ADR
0004 infra-boundary series). This provider is knowledge's stable public API for
that plumbing — a DDD Open Host Service / Published Language.

The returned vector store speaks LangChain's unified ``VectorStore`` interface
(``add_documents`` / ``similarity_search``), so callers stay backend-agnostic —
the concrete backend is resolved from ``settings.VECTOR_STORE_PROVIDER`` inside
knowledge, exactly as before.
"""

from __future__ import annotations

from typing import Any


class DocumentIndexProvider:
    """Driving-side facade over knowledge's embedding + vector-store factories."""

    def embed_pdf(self, **kwargs: Any) -> dict:
        """Embed a PDF into the vector store (passthrough to ``create_embeddings_for_pdf``)."""
        from components.knowledge.infrastructure.adapters.pdf_embeddings import (
            create_embeddings_for_pdf,
        )

        return create_embeddings_for_pdf(**kwargs)

    def embed_document(self, **kwargs: Any) -> dict:
        """Embed a docx/doc into the vector store (passthrough to ``create_embeddings_for_document``)."""
        from components.knowledge.infrastructure.adapters.document_embeddings import (
            create_embeddings_for_document,
        )

        return create_embeddings_for_document(**kwargs)

    def create_embeddings(self, provider: str = "openai") -> Any:
        """Build the embeddings model for *provider* (passthrough to ``EmbeddingsFactory``)."""
        from components.knowledge.infrastructure.factories.embeddings.factory import (
            EmbeddingsFactory,
        )

        return EmbeddingsFactory.create_embeddings(provider=provider)

    def build_vector_store(self, *, embeddings_provider: str | None = None) -> Any:
        """Build the configured vector store (LangChain ``VectorStore`` interface).

        The backend is read from ``settings.VECTOR_STORE_PROVIDER`` inside knowledge;
        the returned store exposes ``add_documents`` / ``similarity_search``. When
        ``embeddings_provider`` is given, that embeddings model is used; when omitted,
        the factory builds its own default (matching a bare ``create_vector_store()``).
        """
        from components.knowledge.infrastructure.factories.vector_stores.factory import (
            VectorStoreFactory,
        )

        if embeddings_provider is None:
            return VectorStoreFactory.create_vector_store()

        from components.knowledge.infrastructure.factories.embeddings.factory import (
            EmbeddingsFactory,
        )

        return VectorStoreFactory.create_vector_store(
            embeddings_instance=EmbeddingsFactory.create_embeddings(provider=embeddings_provider),
        )

    def elasticsearch_client(self) -> Any:
        """Return the Elasticsearch client (passthrough to ``create_elasticsearch_client``)."""
        from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import (
            create_elasticsearch_client,
        )

        return create_elasticsearch_client()

    def index_stats(self, index_name: str = "ai_documents") -> Any:
        """Return index statistics (passthrough to ``get_index_stats``)."""
        from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import (
            get_index_stats,
        )

        return get_index_stats(index_name)


_default = DocumentIndexProvider()


def get_document_index_provider() -> DocumentIndexProvider:
    """Return the default provider — knowledge's published document-indexing seam."""
    return _default
