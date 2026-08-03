"""Unit tests — retrieval ORDERING blends similarity with the P5 rating (ADR 0012).

The tenant-isolation properties are proven in ``test_remediation_retrieval_adapter``;
this file proves the P5 addition: a higher-RATED (more proven) prior of comparable
similarity ranks ABOVE a lower-rated one, while similarity still leads. The fake
store faithfully emulates the vector store's metadata-equality filter AND carries a
per-chunk similarity + ``rating`` metadata, so ordering is proven through the adapter.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.knowledge.application.ports.vector_store_port import RetrievedChunk
from components.remediation.application.ports.remediation_retrieval_port import (
    REMEDIATION_CHUNK_TYPE,
)
from components.remediation.infrastructure.adapters.pgvector_remediation_retrieval_adapter import (
    PgVectorRemediationRetrievalAdapter,
)

pytestmark = pytest.mark.unit

_WS = "11111111-1111-1111-1111-111111111111"


class _ActiveAll:
    """Every queried entry_id is active — isolates ranking from the P5 revoked-drop."""

    def filter_active_entry_ids(self, *, workspace_id, entry_ids):
        return {str(e) for e in entry_ids if e}


class _RankingFakeStore:
    """Returns seeded chunks matching the metadata filters, each with its own
    similarity (``score``) and ``rating`` — so the adapter's blend is under test."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    def search(self, query, *, k=5, filters=None):
        out = []
        for chunk in self._chunks:
            meta = chunk.metadata or {}
            if all(self._matches(meta.get(key), val) for key, val in (filters or {}).items()):
                out.append(chunk)
        return out[:k]

    @staticmethod
    def _matches(actual, expected) -> bool:
        if actual is None:
            return False
        return str(actual) == str(expected)


def _chunk(*, title, similarity, rating, workspace_id=_WS, finding_kind="log_watch"):
    return RetrievedChunk(
        content=f"fix {title}",
        metadata={
            "chunk_type": REMEDIATION_CHUNK_TYPE,
            "workspace_id": workspace_id,
            "finding_kind": finding_kind,
            "language": "python",
            "title": title,
            "summary": "",
            "code": f"{title}()",
            "tags": [],
            "rating": rating,
            "entry_id": str(uuid4()),
        },
        score=similarity,
    )


class TestRetrievalRanking:
    def test_higher_rated_prior_ranks_above_lower_at_equal_similarity(self):
        store = _RankingFakeStore(
            [
                _chunk(title="unproven", similarity=0.9, rating=1),
                _chunk(title="proven", similarity=0.9, rating=12),
            ]
        )
        adapter = PgVectorRemediationRetrievalAdapter(store=store, entry_store=_ActiveAll())

        results = adapter.retrieve_grounding(
            workspace_id=_WS, finding_kind="log_watch", query_text="import error", top_k=2
        )

        assert [r.title for r in results] == ["proven", "unproven"]
        # The rating is carried through for transparency.
        assert results[0].rating == 12

    def test_recurred_prior_negative_rating_sinks_to_the_bottom(self):
        store = _RankingFakeStore(
            [
                _chunk(title="recurred", similarity=0.9, rating=-9),
                _chunk(title="held", similarity=0.9, rating=4),
            ]
        )
        adapter = PgVectorRemediationRetrievalAdapter(store=store, entry_store=_ActiveAll())

        results = adapter.retrieve_grounding(workspace_id=_WS, finding_kind="log_watch", query_text="q", top_k=2)
        assert [r.title for r in results] == ["held", "recurred"]

    def test_similarity_still_leads_over_rating(self):
        # A much-more-similar unproven fix beats a marginally-similar highly-rated one.
        store = _RankingFakeStore(
            [
                _chunk(title="relevant", similarity=0.97, rating=0),
                _chunk(title="marginal", similarity=0.55, rating=50),
            ]
        )
        adapter = PgVectorRemediationRetrievalAdapter(store=store, entry_store=_ActiveAll())

        results = adapter.retrieve_grounding(workspace_id=_WS, finding_kind="log_watch", query_text="q", top_k=2)
        assert results[0].title == "relevant"

    def test_missing_rating_defaults_to_zero_and_still_ranks(self):
        # An old chunk written before P5 (no ``rating`` key) must not break ranking.
        legacy = RetrievedChunk(
            content="legacy",
            metadata={
                "chunk_type": REMEDIATION_CHUNK_TYPE,
                "workspace_id": _WS,
                "finding_kind": "log_watch",
                "title": "legacy",
                "entry_id": str(uuid4()),  # has an entry_id (active); only the rating is absent
            },
            score=0.9,
        )
        store = _RankingFakeStore([legacy, _chunk(title="rated", similarity=0.9, rating=8)])
        adapter = PgVectorRemediationRetrievalAdapter(store=store, entry_store=_ActiveAll())

        results = adapter.retrieve_grounding(workspace_id=_WS, finding_kind="log_watch", query_text="q", top_k=2)
        assert [r.title for r in results] == ["rated", "legacy"]
