"""LangChain-PGVector-backed adapter for ``DocumentRetrievalPort``.

Uploaded PDFs/documents are embedded by ``create_embeddings_for_pdf`` /
``create_embeddings_for_document`` into the LangChain PGVector collection
(``langchain_pg_embedding``, collection ``ai_documents``) with metadata
``{pdf_id | file_id, workspace_id, type, page}`` — a DIFFERENT store from
the workspace-snapshot chunks in ``ai_embedding_chunks``. This adapter is
the read path over that store, filtered to the caller's selected file ids.

Tenancy: the metadata filter always pins ``workspace_id``, so a file id
belonging to another workspace matches nothing — no separate ownership
query needed.
"""

from __future__ import annotations

import logging

from components.knowledge.application.ports.document_retrieval_port import (
    DocumentRetrievalPort,
)
from components.knowledge.application.ports.vector_store_port import (
    RetrievedChunk,
)

logger = logging.getLogger(__name__)


class PgVectorDocumentRetrievalAdapter(DocumentRetrievalPort):
    """Reads uploaded-document chunks from the LangChain PGVector collection."""

    def search(
        self,
        *,
        workspace_id: str,
        query: str,
        file_ids: list[str],
        k: int = 6,
    ) -> list[RetrievedChunk]:
        clean_ids = [str(i) for i in (file_ids or []) if i]
        if not workspace_id or not (query or "").strip() or not clean_ids:
            return []

        # Three chunk families share the collection, keyed differently:
        # PDF uploads tag ``pdf_id`` and docx uploads ``file_id`` (integer
        # File/Pdf pks), while indexed FINANCIAL REPORTS tag ``report_id``
        # (a UUID string — see reports/rag_index_handler). The unified
        # documents list exposes report rows as ``report-<uuid>``, so ids
        # arriving with that prefix select report chunks.
        report_ids = [i.removeprefix("report-") for i in clean_ids if i.startswith("report-")]
        pk_ids = [i for i in clean_ids if not i.startswith("report-")]
        id_branches = []
        if pk_ids:
            id_branches.append({"pdf_id": {"$in": pk_ids}})
            id_branches.append({"file_id": {"$in": pk_ids}})
        if report_ids:
            id_branches.append({"report_id": {"$in": report_ids}})

        try:
            from components.knowledge.infrastructure.factories.vector_stores.factory import (
                VectorStoreFactory,
            )

            store = VectorStoreFactory.create_vector_store()
            # PDF embeds tag chunks with ``pdf_id``; docx embeds with
            # ``file_id``. Both carry ``workspace_id``. langchain_postgres
            # (0.0.17) rejects a ``$or`` mixed with field keys at the top
            # level ("Expected a field but got: $or") — the whole filter
            # must be a single ``$and`` of conditions (verified live
            # 2026-07-13; the mixed form silently returned nothing).
            hits = store.similarity_search_with_score(
                query,
                k=k,
                filter={
                    "$and": [
                        {"workspace_id": {"$eq": str(workspace_id)}},
                        {"$or": id_branches},
                    ]
                },
            )
        except Exception:
            logger.exception(
                "document_retrieval.search_failed workspace_id=%s file_ids=%s",
                workspace_id,
                clean_ids,
            )
            return []

        chunks: list[RetrievedChunk] = []
        for doc, score in hits or []:
            metadata = dict(getattr(doc, "metadata", None) or {})
            # Label the chunk so prompts + provenance can distinguish
            # "author-selected document" from workspace-snapshot context.
            # Document chunks carry page + file id, never section titles.
            if not metadata.get("section_title"):
                page = metadata.get("page")
                metadata["section_title"] = (
                    f"Selected document — page {int(page) + 1}"
                    if isinstance(page, (int, float))
                    else "Selected document"
                )
            metadata.setdefault("section", "selected_document")
            # LangChain PGVector returns cosine DISTANCE (lower = closer);
            # normalise to a similarity-like score so callers can rank
            # uniformly with the snapshot chunks.
            try:
                similarity = 1.0 - float(score)
            except (TypeError, ValueError):
                similarity = 0.0
            chunks.append(
                RetrievedChunk(
                    content=(getattr(doc, "page_content", "") or ""),
                    metadata=metadata,
                    score=similarity,
                )
            )
        return chunks
