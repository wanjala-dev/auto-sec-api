"""Dynamic vector-store provider registry.

Resolves a provider slug to the corresponding ``VectorStorePort`` adapter
at runtime.  All optional backends are registered with ``try / except
ImportError`` so missing packages are silently skipped.

Usage::

    provider = AIVectorStoreProvider()
    vs = provider.get_port("elasticsearch")
    vs = provider.get_port("pinecone", api_key="…")
    vs = provider.get_port("chroma", persist_directory="/data/chroma")
    vs = provider.get_port("faiss")
    vs = provider.get_port("s3", bucket="my-bucket")
"""

from __future__ import annotations

import logging
import os

from components.knowledge.domain.errors import UnsupportedProviderError
from components.knowledge.application.ports.vector_store_port import VectorStorePort

logger = logging.getLogger(__name__)

# Environment variable to choose the default backend at deploy time.
# pgvector is the lean-stack default — Elasticsearch is opt-in via the env
# var. Matches the factory's _resolve_default_provider() so the agents
# controller, knowledge service, and PDF pipeline all agree on which
# backend they're talking to.
_DEFAULT_VECTOR_STORE_SLUG = os.environ.get("VECTOR_STORE_PROVIDER", "pgvector")


class AIVectorStoreProvider:
    """Registry that lazily constructs the right vector-store adapter."""

    _FACTORIES: dict[str, type] = {}

    def __init__(self) -> None:
        if not AIVectorStoreProvider._FACTORIES:
            self._register_builtin_factories()

    # ── Registration ─────────────────────────────────────────────────

    @classmethod
    def _register_builtin_factories(cls) -> None:
        """Register every known adapter; skip those whose deps are missing."""

        # Elasticsearch (always available — core adapter)
        try:
            from components.knowledge.infrastructure.adapters.vector_store.elasticsearch_vector_store_adapter import (
                ElasticsearchVectorStoreAdapter,
            )
            cls._FACTORIES["elasticsearch"] = ElasticsearchVectorStoreAdapter
        except ImportError:
            logger.debug("elasticsearch adapter unavailable (missing elasticsearch-py)")

        # pgvector (PostgreSQL native vector search)
        try:
            from components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter import (
                PgVectorStoreAdapter,
            )
            cls._FACTORIES["pgvector"] = PgVectorStoreAdapter
            cls._FACTORIES["postgres"] = PgVectorStoreAdapter
        except ImportError:
            logger.debug("pgvector adapter unavailable")

        # Pinecone
        try:
            from components.knowledge.infrastructure.adapters.vector_store.pinecone_vector_store_adapter import (
                PineconeVectorStoreAdapter,
            )
            cls._FACTORIES["pinecone"] = PineconeVectorStoreAdapter
        except ImportError:
            logger.debug("pinecone adapter unavailable (missing pinecone-client)")

        # ChromaDB
        try:
            from components.knowledge.infrastructure.adapters.vector_store.chroma_vector_store_adapter import (
                ChromaVectorStoreAdapter,
            )
            cls._FACTORIES["chroma"] = ChromaVectorStoreAdapter
        except ImportError:
            logger.debug("chroma adapter unavailable (missing chromadb)")

        # Meta FAISS (local)
        try:
            from components.knowledge.infrastructure.adapters.vector_store.faiss_vector_store_adapter import (
                FAISSVectorStoreAdapter,
            )
            cls._FACTORIES["faiss"] = FAISSVectorStoreAdapter
        except ImportError:
            logger.debug("faiss adapter unavailable (missing faiss-cpu)")

        # FAISS on S3 (durable)
        try:
            from components.knowledge.infrastructure.adapters.vector_store.s3_vector_store_adapter import (
                S3VectorStoreAdapter,
            )
            cls._FACTORIES["s3"] = S3VectorStoreAdapter
        except ImportError:
            logger.debug("s3 vector-store adapter unavailable (missing boto3 / faiss-cpu)")

    # ── Public API ───────────────────────────────────────────────────

    def get_port(self, provider: str | None = None, **kwargs) -> VectorStorePort:
        """Return the adapter for *provider* (defaults to ``VECTOR_STORE_PROVIDER`` env var)."""
        slug = provider or _DEFAULT_VECTOR_STORE_SLUG
        factory = self._FACTORIES.get(slug)
        if factory is None:
            raise UnsupportedProviderError("vector store", slug, list(self._FACTORIES))
        return factory(**kwargs)

    @classmethod
    def register(cls, slug: str, factory: type) -> None:
        """Register an external adapter at runtime (plugin pattern)."""
        cls._FACTORIES[slug] = factory

    def available_providers(self) -> list[str]:
        return sorted(self._FACTORIES)
