"""Provider-aware implementation of ``KnowledgeTextIngestPort``.

Reads ``VECTOR_STORE_PROVIDER`` from the environment (defaults to
``elasticsearch``) and writes chunks to the corresponding backend via
``VectorStoreFactory``. Currently supports ``elasticsearch`` and
``pgvector`` — the ingest API is the same; only the delete path differs.

Replace semantics: chunks are written with deterministic ids derived
from ``document_key`` so re-indexing the same document overwrites prior
chunks in place.

For ``elasticsearch``, ``delete_by_key`` runs a ``delete_by_query`` via
the ES client before adding new chunks — catches orphans when a newly
shrunken corpus leaves fewer chunks than before.

For ``pgvector``, delete-by-metadata is not natively supported by the
LangChain PGVector adapter without raw SQL. Upsert via deterministic
ids handles every regeneration case *except* a shrinking chunk count,
which leaves orphaned chunks behind. Acceptable for v1 — we regenerate
the full report each time, and orphan chunks still point at the same
``document_key`` so retrieval filtering is unaffected.
"""

from __future__ import annotations

import logging
import os

from components.knowledge.application.ports.knowledge_text_ingest_port import (
    KnowledgeTextIngestPort,
)


logger = logging.getLogger(__name__)


_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 100
_DEFAULT_INDEX = "ai_documents"


class KnowledgeTextIngestAdapter(KnowledgeTextIngestPort):
    """``provider=None`` defers to VectorStoreFactory's settings-based
    default (pgvector on the lean stack) — the adapter's old private env
    fallback defaulted to ELASTICSEARCH, so ingest (reports) and retrieval
    (documents) could land on DIFFERENT stores; wherever the env var was
    unset, report RAG indexing crashed on a missing elasticsearch and
    every report silently stayed unindexed (caught 2026-07-14 running the
    backfill locally)."""

    def __init__(self, provider: str | None = None) -> None:
        self._provider = provider.lower() if provider else None

    def index_text(
        self,
        *,
        text: str,
        document_key: str,
        metadata: dict,
    ) -> int:
        if not text or not text.strip():
            return 0
        if not document_key:
            raise ValueError("document_key is required for text ingestion.")

        from langchain.text_splitter import RecursiveCharacterTextSplitter
        from langchain_core.documents import Document

        from components.knowledge.infrastructure.factories.embeddings.factory import (
            EmbeddingsFactory,
        )
        from components.knowledge.infrastructure.factories.vector_stores.factory import (
            VectorStoreFactory,
        )

        try:
            self.delete_by_key(document_key=document_key)
        except Exception:  # noqa: BLE001
            logger.exception(
                "text_ingest_pre_delete_failed document_key=%s provider=%s",
                document_key,
                self._provider,
            )

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHUNK_SIZE,
            chunk_overlap=_CHUNK_OVERLAP,
        )
        base_metadata = {**metadata, "document_key": document_key}
        chunks = splitter.split_documents(
            [Document(page_content=text, metadata=base_metadata)]
        )
        if not chunks:
            return 0

        for idx, chunk in enumerate(chunks):
            chunk.metadata.update(
                {
                    "chunk_index": idx,
                    "page": idx + 1,
                    "text": chunk.page_content,
                }
            )

        ids = [f"{document_key}__chunk_{i}" for i in range(len(chunks))]

        store = VectorStoreFactory.create_vector_store(
            provider=self._provider,
            embeddings_instance=EmbeddingsFactory.create_embeddings(provider="openai"),
        )
        store.add_documents(chunks, ids=ids)
        logger.info(
            "knowledge_text_ingest_indexed document_key=%s chunks=%d provider=%s",
            document_key,
            len(chunks),
            self._provider,
        )
        return len(chunks)

    def delete_by_key(self, *, document_key: str) -> int:
        if not document_key:
            return 0
        if self._provider == "elasticsearch":
            return self._delete_by_key_elasticsearch(document_key)
        if self._provider in {"pgvector", "postgres"}:
            return self._delete_by_key_pgvector(document_key)
        logger.info(
            "knowledge_text_ingest_delete_skipped document_key=%s provider=%s reason=unsupported",
            document_key,
            self._provider,
        )
        return 0

    # ── Provider-specific delete implementations ─────────────────────

    def _delete_by_key_elasticsearch(self, document_key: str) -> int:
        from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import (
            create_elasticsearch_client,
        )

        index = os.environ.get("ELASTICSEARCH_INDEX_NAME", _DEFAULT_INDEX)
        try:
            client = create_elasticsearch_client()
            if not client.indices.exists(index=index):
                return 0
            response = client.delete_by_query(
                index=index,
                body={
                    "query": {
                        "term": {"metadata.document_key.keyword": document_key}
                    }
                },
                ignore_unavailable=True,
                conflicts="proceed",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "knowledge_text_ingest_delete_failed document_key=%s", document_key
            )
            return 0
        deleted = int(response.get("deleted", 0) or 0)
        logger.info(
            "knowledge_text_ingest_deleted document_key=%s chunks=%d provider=elasticsearch",
            document_key,
            deleted,
        )
        return deleted

    def _delete_by_key_pgvector(self, document_key: str) -> int:
        # LangChain PGVector exposes ``delete(filter=...)`` on newer
        # versions of ``langchain-postgres``. Fall back to a no-op if the
        # running version doesn't support it — upsert via deterministic
        # ids still gives correct replacement for same-or-larger chunk
        # counts, so retrieval stays consistent with the latest corpus.
        try:
            from components.knowledge.infrastructure.factories.vector_stores.pgvector import (
                build_pgvector_store,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "knowledge_text_ingest_pgvector_store_unavailable document_key=%s",
                document_key,
            )
            return 0

        try:
            store = build_pgvector_store()
            # ``delete`` with a metadata filter is supported from
            # langchain-postgres 0.0.12+. On older versions this raises
            # ``TypeError`` or ``NotImplementedError`` — swallow and
            # rely on upsert semantics.
            store.delete(filter={"document_key": document_key})
        except (TypeError, NotImplementedError):
            logger.info(
                "knowledge_text_ingest_pgvector_delete_unsupported document_key=%s",
                document_key,
            )
            return 0
        except Exception:  # noqa: BLE001
            logger.exception(
                "knowledge_text_ingest_delete_failed document_key=%s provider=pgvector",
                document_key,
            )
            return 0

        logger.info(
            "knowledge_text_ingest_deleted document_key=%s provider=pgvector",
            document_key,
        )
        return 0
