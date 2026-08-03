"""pgvector adapter for ``RemediationRetrievalPort`` (ADR 0012 P4, D4).

Reads the vetted-fix corpus back out of the ``knowledge`` pgvector store
(``ai_embedding_chunks``) — reusing knowledge's own ``VectorStorePort`` through its
application-layer provider (``AIVectorStoreProvider``), NOT by importing knowledge
infrastructure (that would breach the cross-context boundary). No second vector
store.

Tenant isolation (D4) is the load-bearing property and it is enforced at the DATA
layer, not by a prompt: every search pins ``metadata.workspace_id = <this ws>`` AND
``metadata.chunk_type = "remediation_entry"``. The vector store renders these as SQL
equality predicates (``metadata->>key = value``); a chunk whose metadata lacks a key
yields SQL NULL and fails the predicate — so cross-workspace entries and non-
remediation chunks are both excluded, fail-closed. An empty ``workspace_id`` short-
circuits to ``[]`` and never issues an unscoped query.

Retrieval GROUNDS a candidate; it never authorizes (D2). This adapter only reads —
it holds no write path — so the corpus's single-writer invariant (D1) is untouched.
"""

from __future__ import annotations

import logging

from components.remediation.application.ports.remediation_retrieval_port import (
    REMEDIATION_CHUNK_TYPE,
    RemediationGroundingDTO,
    RemediationRetrievalPort,
)

logger = logging.getLogger(__name__)


class PgVectorRemediationRetrievalAdapter(RemediationRetrievalPort):
    """Reads remediation-entry chunks from ``ai_embedding_chunks`` (D4-scoped)."""

    def __init__(self, store=None) -> None:
        # ``store`` is an injected knowledge ``VectorStorePort`` (tests wire a fake
        # that honours the metadata filters). Production resolves the pgvector
        # adapter lazily through knowledge's application provider.
        self._store = store

    def _vector_store(self):
        if self._store is not None:
            return self._store
        from components.knowledge.application.providers.ai_vector_store_provider import (
            AIVectorStoreProvider,
        )

        self._store = AIVectorStoreProvider().get_port("pgvector")
        return self._store

    def retrieve_grounding(
        self,
        *,
        workspace_id: str,
        finding_kind: str,
        query_text: str,
        top_k: int = 3,
    ) -> list[RemediationGroundingDTO]:
        # D4: no workspace, no retrieval — never fall through to an unscoped search.
        if not (workspace_id and str(workspace_id).strip()):
            return []
        if not (query_text or "").strip():
            return []

        # MANDATORY tenant + type predicates. ``finding_kind`` narrows to the same
        # class of finding (relevance); ``workspace_id`` + ``chunk_type`` are the
        # isolation floor and are always present.
        filters: dict = {
            "chunk_type": REMEDIATION_CHUNK_TYPE,
            "workspace_id": str(workspace_id),
        }
        if finding_kind:
            filters["finding_kind"] = str(finding_kind)

        try:
            chunks = self._vector_store().search(query_text, k=max(1, int(top_k)), filters=filters)
        except Exception:
            logger.exception(
                "remediation_retrieval_failed workspace_id=%s finding_kind=%s (grounding=[])",
                workspace_id,
                finding_kind,
            )
            return []

        results = [self._to_dto(chunk) for chunk in chunks]
        # Defence in depth against a mis-stamped / mis-filtering backend: drop any
        # row whose workspace_id does not match ours. The DB filter is the control;
        # this is a belt-and-suspenders check so a retrieval can never leak across
        # tenants even if the store's filter were somehow bypassed.
        safe = [
            r
            for (r, chunk) in zip(results, chunks)
            if str((chunk.metadata or {}).get("workspace_id")) == str(workspace_id)
        ]
        logger.info(
            "remediation_retrieval workspace_id=%s finding_kind=%s returned=%d",
            workspace_id,
            finding_kind,
            len(safe),
        )
        return safe

    @staticmethod
    def _to_dto(chunk) -> RemediationGroundingDTO:
        meta = chunk.metadata or {}
        tags = meta.get("tags")
        if isinstance(tags, (list, tuple)):
            tags_tuple = tuple(str(t) for t in tags)
        elif isinstance(tags, str) and tags:
            tags_tuple = tuple(t for t in tags.split(",") if t)
        else:
            tags_tuple = ()
        return RemediationGroundingDTO(
            finding_kind=str(meta.get("finding_kind") or ""),
            language=str(meta.get("language") or ""),
            title=str(meta.get("title") or ""),
            summary=str(meta.get("summary") or ""),
            code=str(meta.get("code") or ""),
            tags=tags_tuple,
            score=float(getattr(chunk, "score", 0.0) or 0.0),
        )
