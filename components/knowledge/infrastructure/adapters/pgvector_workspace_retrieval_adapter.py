"""pgvector-backed adapter for ``WorkspaceRetrievalPort``.

Delegates to ``PgVectorStoreAdapter.scoped_search`` with a metadata filter
pinning results to the current workspace and the workspace-snapshot chunk
source (so retrieval never returns, say, a PDF chunk that happens to share
a workspace id).
"""

from __future__ import annotations

from components.knowledge.application.ports.vector_store_port import (
    RetrievedChunk,
)
from components.knowledge.application.ports.workspace_retrieval_port import (
    WorkspaceRetrievalPort,
)
from components.knowledge.domain.value_objects.retrieval_sensitivity import (
    allowed_sensitivities_for_role,
)
from components.knowledge.infrastructure.adapters.pgvector_workspace_index_adapter import (
    CHUNK_SOURCE,
)


class PgVectorWorkspaceRetrievalAdapter(WorkspaceRetrievalPort):
    """Reads workspace-snapshot chunks from ``ai_embedding_chunks``."""

    def search(
        self,
        *,
        workspace_id: str,
        query: str,
        k: int = 5,
        viewer_role: str | None = None,
    ) -> list[RetrievedChunk]:
        if not workspace_id or not (query or "").strip():
            return []

        if not self._pgvector_available():
            # Environments without the pgvector extension (e.g. pytest
            # skips migrations) can't run the cosine-distance SQL.  Degrade
            # to an empty result rather than raising — retrieval simply
            # returns "no indexed context" upstream.
            return []

        from components.knowledge.infrastructure.adapters.vector_store.pgvector_store_adapter import (
            PgVectorStoreAdapter,
        )

        store = PgVectorStoreAdapter()
        # SEE-199 — role-scoped retrieval.  Cross-workspace isolation is
        # pinned by ``workspace_id``; the *sensitivity* filter adds the
        # intra-workspace tier gate so a low-privilege member can't pull
        # owner/admin-only rollups (donation totals, pipeline entities)
        # through the agent's broad retrieval.  A list value renders as
        # ``metadata->>'sensitivity' = ANY(...)``; chunks with no tier
        # stamped fail the ANY (NULL) and are excluded (fail-closed) —
        # legacy rows are backfilled by migration.
        allowed = list(allowed_sensitivities_for_role(viewer_role))
        # Tier 3 #11 — hybrid search via Reciprocal Rank Fusion.  The
        # vector half catches semantic matches ("mission" → "vision /
        # purpose"); the keyword half catches exact-match queries
        # (recipient names, donor emails, campaign slugs) the vector
        # path misses.  RRF merges by rank, not score, so the two
        # ranker scales don't need to be normalised.
        return store.hybrid_search_rrf(
            query,
            k=k,
            filters={
                "workspace_id": str(workspace_id),
                "source": CHUNK_SOURCE,
                "sensitivity": allowed,
            },
        )

    @staticmethod
    def _pgvector_available() -> bool:
        from django.db import connection

        if connection.vendor != "postgresql":
            return False
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1"
            )
            return cursor.fetchone() is not None
