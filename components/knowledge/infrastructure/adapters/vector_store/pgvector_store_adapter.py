"""pgvector adapter — stores and retrieves embeddings using PostgreSQL + pgvector.

Uses the ``vector`` column type from the pgvector extension and performs
cosine-similarity search via the ``<=>`` operator.  Zero dependency on
Elasticsearch — only requires the main application database with pgvector
installed.

Requires:
    - pgvector PostgreSQL extension: ``CREATE EXTENSION IF NOT EXISTS vector;``
    - ``langchain-postgres`` package (``pip install langchain-postgres``)
    - The ``EmbeddingChunk`` ORM model in ``infrastructure.persistence.ai.models``
"""

from __future__ import annotations

import json
import logging
import os

from components.knowledge.application.ports.vector_store_port import (
    RetrievedChunk,
    SearchMode,
    VectorStorePort,
)

logger = logging.getLogger(__name__)

# Default embedding dimension — matches OpenAI text-embedding-ada-002 / text-embedding-3-small
_EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIMENSION", "1536"))


def _chunk_identity(chunk: RetrievedChunk) -> str:
    """Stable identity for a chunk across two ranked lists.

    The pgvector rows don't expose an id column in the current
    ``ai_embedding_chunks`` schema reads, but content is unique per
    chunk inside one workspace.  Hashing content keeps the key short
    while preserving uniqueness for RRF dedup.

    A future schema change that surfaces the chunk pk through the
    SELECT can swap this for the pk; the public contract of
    ``hybrid_search_rrf`` does not depend on the identity helper.
    """
    return chunk.content or ""


def _merge_via_rrf(
    *,
    rankings: tuple[list[RetrievedChunk], ...],
    rrf_constant: int,
    top_k: int,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion over an arbitrary number of ranked lists.

    Each chunk's RRF score is the sum, over every ranker it appears
    in, of ``1 / (rrf_constant + rank)`` where ``rank`` is 1-indexed.
    Chunks present in only one ranker still contribute one term;
    chunks present in multiple rankers get a multi-term boost — which
    is exactly the desired behaviour (consensus across rankers is
    stronger signal than a single ranker's top-1).
    """
    scores: dict[str, float] = {}
    representatives: dict[str, RetrievedChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            key = _chunk_identity(chunk)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_constant + rank)
            representatives.setdefault(key, chunk)

    ordered_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
    merged: list[RetrievedChunk] = []
    for key in ordered_keys[:top_k]:
        chunk = representatives[key]
        # Stash the fused score on a fresh RetrievedChunk so callers
        # that inspect ``.score`` see the merged value, not the
        # individual ranker's score.
        merged.append(
            RetrievedChunk(
                content=chunk.content,
                metadata=chunk.metadata,
                score=round(scores[key], 6),
            )
        )
    return merged


def _decode_metadata(value) -> dict:
    """Normalise ``ai_embedding_chunks.metadata`` from a raw cursor.

    Django's raw cursor returns ``jsonb`` columns as strings on psycopg,
    unlike the ORM which auto-decodes them.  Downstream code treats
    metadata as a dict (``metadata.get("workspace_id")``), so we decode
    here — once, at the adapter boundary.
    """
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


class PgVectorStoreAdapter(VectorStorePort):
    """Vector store backed by PostgreSQL + pgvector extension.

    Stores embeddings in the ``ai_embedding_chunks`` table and searches
    via cosine similarity (``<=>``) with optional metadata filters.
    """

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory

        embeddings = EmbeddingsFactory.create_embeddings(provider="openai")
        query_vector = embeddings.embed_query(query)

        return self._vector_search(query_vector, k=k, filters=filters)

    def hybrid_search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
        mode: SearchMode = SearchMode.HYBRID,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[RetrievedChunk]:
        from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory

        if mode == SearchMode.KEYWORD:
            return self._keyword_search(query, k=k, filters=filters)

        if mode == SearchMode.VECTOR:
            return self.search(query, k=k, filters=filters)

        # Hybrid: combine vector similarity + full-text rank
        embeddings = EmbeddingsFactory.create_embeddings(provider="openai")
        query_vector = embeddings.embed_query(query)

        return self._hybrid_search(
            query,
            query_vector,
            k=k,
            filters=filters,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )

    def hybrid_search_rrf(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
        fetch_multiplier: int = 4,
        rrf_constant: int = 60,
    ) -> list[RetrievedChunk]:
        """Tier 3 #11 — hybrid search via Reciprocal Rank Fusion.

        Runs vector and keyword searches independently, then merges
        their results by rank (NOT raw score — vector cosine and
        ts_rank_cd live on different scales, so weighted sums don't
        compose).  RRF score for each chunk:

            score = sum over each ranker R of: 1 / (rrf_constant + rank_R)

        Higher is better.  ``rrf_constant`` defaults to 60 per the
        original RRF paper (Cormack, Clarke, Buettcher 2009); larger
        values flatten the rank curve and reduce the influence of
        top-1 results in either ranker.

        The keyword path tolerates ``websearch_to_tsquery`` syntax
        errors and zero-result queries — both fall back to pure
        vector mode.  The vector path is the floor: if hybrid returns
        nothing for some reason, we still return vector results.
        """
        try:
            from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory

            embeddings = EmbeddingsFactory.create_embeddings(provider="openai")
            query_vector = embeddings.embed_query(query)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "hybrid_search_rrf: embedding failed, "
                "falling back to keyword-only path",
                exc_info=True,
            )
            return self._keyword_search(query, k=k, filters=filters)[:k]

        fetch_k = max(k, k * max(fetch_multiplier, 1))
        vector_hits = self._vector_search(
            query_vector, k=fetch_k, filters=filters
        )
        try:
            keyword_hits = self._keyword_search(
                query, k=fetch_k, filters=filters
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "hybrid_search_rrf: keyword search failed (likely "
                "tsquery syntax), falling back to vector-only path",
                exc_info=True,
            )
            return vector_hits[:k]

        # No keyword matches → keyword ranker contributes 0; return
        # pure vector top-k.  Common case for queries with no overlap
        # with the corpus vocabulary.
        if not keyword_hits:
            return vector_hits[:k]
        if not vector_hits:
            return keyword_hits[:k]

        return _merge_via_rrf(
            rankings=(vector_hits, keyword_hits),
            rrf_constant=rrf_constant,
            top_k=k,
        )

    def has_indexed_content(
        self,
        *,
        pdf_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        from infrastructure.persistence.ai.models import EmbeddingChunk

        qs = EmbeddingChunk.objects.all()
        if pdf_id:
            qs = qs.filter(metadata__pdf_id=str(pdf_id))
        if workspace_id:
            qs = qs.filter(metadata__workspace_id=str(workspace_id))
        if user_id:
            qs = qs.filter(metadata__user_id=str(user_id))
        return qs.exists()

    def provider_name(self) -> str:
        return "pgvector"

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _build_filter_clause(filters: dict | None) -> tuple[str, list]:
        """Build a SQL WHERE fragment from metadata filters.

        A scalar value renders as equality (``metadata->>key = value``); a
        list/tuple/set value renders as set membership
        (``metadata->>key = ANY(ARRAY[...])``) so callers can pass, e.g., the
        set of sensitivity tiers a viewer may read (SEE-199). A chunk whose
        metadata lacks *key* yields SQL NULL, which fails both ``=`` and
        ``ANY`` — so an absent tier is excluded, not leaked (fail-closed).

        Returns (sql_fragment, params) where sql_fragment is empty string
        when there are no filters.
        """
        if not filters:
            return "", []

        clauses: list[str] = []
        params: list = []
        for key, value in filters.items():
            if isinstance(value, (list, tuple, set)):
                clauses.append("metadata->>%s = ANY(%s)")
                params.extend([key, [str(v) for v in value]])
            else:
                clauses.append("metadata->>%s = %s")
                params.extend([key, str(value)])

        return " AND " + " AND ".join(clauses), params

    def _vector_search(
        self,
        query_vector: list[float],
        *,
        k: int = 5,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        from django.db import connection

        filter_sql, filter_params = self._build_filter_clause(filters)

        sql = f"""
            SELECT content, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM ai_embedding_chunks
            WHERE embedding IS NOT NULL
            {filter_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        params = [str(query_vector), *filter_params, str(query_vector), k]

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        return [
            RetrievedChunk(
                content=row[0],
                metadata=_decode_metadata(row[1]),
                score=float(row[2]) if row[2] is not None else 0.0,
            )
            for row in rows
        ]

    def _keyword_search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        from django.db import connection

        filter_sql, filter_params = self._build_filter_clause(filters)

        sql = f"""
            SELECT content, metadata,
                   ts_rank_cd(
                       to_tsvector('english', content),
                       websearch_to_tsquery('english', %s)
                   ) AS score
            FROM ai_embedding_chunks
            WHERE to_tsvector('english', content) @@ websearch_to_tsquery('english', %s)
            {filter_sql}
            ORDER BY score DESC
            LIMIT %s
        """
        params = [query, query, *filter_params, k]

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        return [
            RetrievedChunk(
                content=row[0],
                metadata=_decode_metadata(row[1]),
                score=float(row[2]) if row[2] is not None else 0.0,
            )
            for row in rows
        ]

    def _hybrid_search(
        self,
        query: str,
        query_vector: list[float],
        *,
        k: int = 5,
        filters: dict | None = None,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[RetrievedChunk]:
        from django.db import connection

        filter_sql, filter_params = self._build_filter_clause(filters)

        sql = f"""
            SELECT content, metadata,
                   (
                       %s * (1 - (embedding <=> %s::vector))
                       + %s * COALESCE(
                           ts_rank_cd(
                               to_tsvector('english', content),
                               websearch_to_tsquery('english', %s)
                           ), 0
                       )
                   ) AS score
            FROM ai_embedding_chunks
            WHERE embedding IS NOT NULL
            {filter_sql}
            ORDER BY score DESC
            LIMIT %s
        """
        params = [
            vector_weight,
            str(query_vector),
            keyword_weight,
            query,
            *filter_params,
            k,
        ]

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        return [
            RetrievedChunk(
                content=row[0],
                metadata=_decode_metadata(row[1]),
                score=float(row[2]) if row[2] is not None else 0.0,
            )
            for row in rows
        ]
