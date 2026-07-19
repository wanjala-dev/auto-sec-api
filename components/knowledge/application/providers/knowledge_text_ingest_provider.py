"""Composition root for ``KnowledgeTextIngestPort``.

Returns the single provider-aware ``KnowledgeTextIngestAdapter``, which
dispatches to elasticsearch or pgvector based on the
``VECTOR_STORE_PROVIDER`` environment variable. Mirrors the runtime
resolution pattern in ``AIVectorStoreProvider`` so ingest and retrieval
agree on the backend.
"""

from __future__ import annotations

from components.knowledge.application.ports.knowledge_text_ingest_port import (
    KnowledgeTextIngestPort,
)
from components.knowledge.infrastructure.adapters.knowledge_text_ingest_adapter import (
    KnowledgeTextIngestAdapter,
)


class KnowledgeTextIngestProvider:
    def build_port(self) -> KnowledgeTextIngestPort:
        return KnowledgeTextIngestAdapter()
