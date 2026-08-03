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
from components.remediation.domain.services.remediation_ranking_policy import (
    RemediationRankingPolicy,
)

logger = logging.getLogger(__name__)

# Pool sizing for the rating re-rank: fetch up to ``k * factor`` (capped) candidates
# by similarity, blend in the rating, then truncate to k. A wider pool lets a proven
# fix overtake a marginally-more-similar unproven one; the cap bounds the read.
_RANK_POOL_FACTOR = 4
_RANK_POOL_MAX = 50


def _rating_of(chunk) -> int:
    try:
        return int((chunk.metadata or {}).get("rating") or 0)
    except (TypeError, ValueError):
        return 0


class PgVectorRemediationRetrievalAdapter(RemediationRetrievalPort):
    """Reads remediation-entry chunks from ``ai_embedding_chunks`` (D4-scoped)."""

    def __init__(self, store=None, entry_store=None) -> None:
        # ``store`` is an injected knowledge ``VectorStorePort`` (tests wire a fake
        # that honours the metadata filters). Production resolves the pgvector
        # adapter lazily through knowledge's application provider.
        self._store = store
        # ``entry_store`` is the remediation ``RemediationEntryStorePort`` used for
        # the ACTIVE-status cross-check (P5): retrieval drops any candidate whose
        # entry has been revoked (soft-deleted), so the soft-delete — not the
        # fragile embedding-delete — is the authority on retrievability.
        self._entry_store = entry_store

    def _vector_store(self):
        if self._store is not None:
            return self._store
        from components.knowledge.application.providers.ai_vector_store_provider import (
            AIVectorStoreProvider,
        )

        self._store = AIVectorStoreProvider().get_port("pgvector")
        return self._store

    def _entries(self):
        if self._entry_store is not None:
            return self._entry_store
        from components.remediation.application.providers.remediation_provider import (
            build_remediation_store,
        )

        self._entry_store = build_remediation_store()
        return self._entry_store

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

        k = max(1, int(top_k))
        # Over-fetch a POOL so the rating blend can re-rank: the vector store returns
        # its top-N by pure SIMILARITY, but a slightly-less-similar but far
        # better-PROVEN fix should be able to overtake within the window. We then
        # blend + truncate to k. Bounded so a cold/huge library never over-reads.
        pool = min(_RANK_POOL_MAX, max(k, k * _RANK_POOL_FACTOR))
        try:
            chunks = self._vector_store().search(query_text, k=pool, filters=filters)
        except Exception:
            logger.exception(
                "remediation_retrieval_failed workspace_id=%s finding_kind=%s (grounding=[])",
                workspace_id,
                finding_kind,
            )
            return []

        # Defence in depth against a mis-stamped / mis-filtering backend: drop any
        # row whose workspace_id does not match ours. The DB filter is the control;
        # this is a belt-and-suspenders check so a retrieval can never leak across
        # tenants even if the store's filter were somehow bypassed.
        safe_chunks = [
            chunk for chunk in chunks if str((chunk.metadata or {}).get("workspace_id")) == str(workspace_id)
        ]

        # ACTIVE-status authority check (P5): the vector store lags the corpus — a
        # revoked entry's chunk can still be present if the embedding-delete failed
        # or in the window before it runs. So cross-check every candidate against the
        # ``.active`` RemediationEntry store (batch, workspace-scoped, bounded to the
        # pool) and DROP any whose entry is not active. A chunk with no ``entry_id``
        # can't be verified ⇒ dropped (fail-closed). This makes the soft-delete —
        # not the fragile second-system embedding-delete — the authority on whether
        # a fix is retrievable, so a revoked fix is unretrievable regardless.
        safe_chunks = self._drop_revoked(workspace_id=str(workspace_id), chunks=safe_chunks)

        # Blend similarity + DERIVED rating, then take the top k. Similarity leads;
        # the rating (P5) lifts proven fixes and sinks recurred ones within the pool.
        ranked = sorted(
            safe_chunks,
            key=lambda c: RemediationRankingPolicy.blend_rank(
                similarity=float(getattr(c, "score", 0.0) or 0.0),
                rating=_rating_of(c),
            ),
            reverse=True,
        )
        results = [self._to_dto(chunk) for chunk in ranked[:k]]
        logger.info(
            "remediation_retrieval workspace_id=%s finding_kind=%s pool=%d returned=%d",
            workspace_id,
            finding_kind,
            len(safe_chunks),
            len(results),
        )
        return results

    def _drop_revoked(self, *, workspace_id: str, chunks: list) -> list:
        """Keep only chunks whose ``entry_id`` is an ACTIVE (non-revoked) entry.

        A chunk without an ``entry_id`` is dropped (can't be verified → fail-closed).
        If the active-status check itself fails, fail-closed to ``[]`` — a cold/broken
        cross-check must never risk surfacing a revoked fix."""
        entry_ids = [str((c.metadata or {}).get("entry_id") or "") for c in chunks]
        pairs = [(c, eid) for c, eid in zip(chunks, entry_ids) if eid]
        if not pairs:
            return []
        try:
            active = self._entries().filter_active_entry_ids(
                workspace_id=workspace_id, entry_ids=[eid for _, eid in pairs]
            )
        except Exception:
            logger.exception(
                "remediation_retrieval_active_check_failed workspace_id=%s (fail-closed grounding=[])",
                workspace_id,
            )
            return []
        kept = [c for c, eid in pairs if eid in active]
        dropped = len(chunks) - len(kept)
        if dropped:
            logger.info(
                "remediation_retrieval_dropped_revoked workspace_id=%s dropped=%d",
                workspace_id,
                dropped,
            )
        return kept

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
            rating=_rating_of(chunk),
        )
