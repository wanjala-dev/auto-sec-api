"""Unit tests — retrieval is per-workspace filtered (ADR 0012 D4 tenant isolation).

THE DECISIVE SECURITY TEST. A shared RAG index leaks ~100% cross-tenant on a
targeted probe unless isolation is enforced BELOW the prompt (ADR 0012 D4). The
``PgVectorRemediationRetrievalAdapter`` must always pin ``metadata.workspace_id`` (+
``chunk_type``) as a data-layer filter. Here a fake ``VectorStorePort`` faithfully
emulates the real metadata-equality SQL (``metadata->>key = value``, list → ANY), so
"workspace A never retrieves workspace B's entries" is proven end-to-end through the
adapter, not merely asserted about a mock.
"""

from __future__ import annotations

import pytest

from components.knowledge.application.ports.vector_store_port import RetrievedChunk
from components.remediation.application.ports.remediation_retrieval_port import (
    REMEDIATION_CHUNK_TYPE,
)
from components.remediation.infrastructure.adapters.pgvector_remediation_retrieval_adapter import (
    PgVectorRemediationRetrievalAdapter,
)


class _FilteringFakeStore:
    """Emulates PgVectorStoreAdapter.search filter semantics over a seeded corpus.

    A scalar filter is equality; a list/tuple filter is membership. A chunk missing
    a filtered key fails the predicate (fail-closed) — exactly the real SQL. Records
    every filter set it was called with so tests can assert the mandatory predicates.
    """

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.filter_calls: list[dict] = []

    def search(self, query, *, k=5, filters=None):
        self.filter_calls.append(dict(filters or {}))
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
        if isinstance(expected, (list, tuple, set)):
            return str(actual) in {str(v) for v in expected}
        return str(actual) == str(expected)


def _chunk(*, workspace_id, finding_kind="log_watch", title="Fix", code="alias = Real"):
    return RetrievedChunk(
        content=f"Remediation for {finding_kind}: {title}",
        metadata={
            "chunk_type": REMEDIATION_CHUNK_TYPE,
            "workspace_id": workspace_id,
            "finding_kind": finding_kind,
            "language": "python",
            "title": title,
            "summary": "did this before",
            "code": code,
            "tags": ["import"],
        },
        score=0.9,
    )


_WS_A = "11111111-1111-1111-1111-111111111111"
_WS_B = "22222222-2222-2222-2222-222222222222"


@pytest.mark.unit
class TestRemediationRetrievalTenantIsolation:
    def test_workspace_a_never_retrieves_workspace_b_entries(self):
        # Both workspaces have a same-kind, same-content entry — the worst case for
        # organic cross-tenant leakage. Isolation must come from the workspace_id
        # filter, not from content dissimilarity.
        store = _FilteringFakeStore(
            [
                _chunk(workspace_id=_WS_A, title="A's fix", code="a_fix()"),
                _chunk(workspace_id=_WS_B, title="B's fix", code="b_fix()"),
            ]
        )
        adapter = PgVectorRemediationRetrievalAdapter(store=store)

        results = adapter.retrieve_grounding(workspace_id=_WS_A, finding_kind="log_watch", query_text="import error")

        assert len(results) == 1
        assert results[0].title == "A's fix"
        assert results[0].code == "a_fix()"
        # The mandatory isolation predicates were pushed to the data layer.
        assert store.filter_calls[0]["workspace_id"] == _WS_A
        assert store.filter_calls[0]["chunk_type"] == REMEDIATION_CHUNK_TYPE

    def test_empty_workspace_returns_nothing_and_never_queries(self):
        # D4 fail-closed: no workspace → no retrieval. A missing scope must NEVER
        # fall through to an unscoped (cross-tenant) search.
        store = _FilteringFakeStore([_chunk(workspace_id=_WS_A)])
        adapter = PgVectorRemediationRetrievalAdapter(store=store)

        assert adapter.retrieve_grounding(workspace_id="", finding_kind="log_watch", query_text="x") == []
        assert store.filter_calls == []

    def test_empty_query_returns_nothing(self):
        store = _FilteringFakeStore([_chunk(workspace_id=_WS_A)])
        adapter = PgVectorRemediationRetrievalAdapter(store=store)
        assert adapter.retrieve_grounding(workspace_id=_WS_A, finding_kind="log_watch", query_text="  ") == []

    def test_maps_chunk_metadata_to_grounding_dto(self):
        store = _FilteringFakeStore([_chunk(workspace_id=_WS_A, title="T", code="c()")])
        adapter = PgVectorRemediationRetrievalAdapter(store=store)

        [dto] = adapter.retrieve_grounding(workspace_id=_WS_A, finding_kind="log_watch", query_text="q")

        assert dto.title == "T"
        assert dto.code == "c()"
        assert dto.language == "python"
        assert dto.finding_kind == "log_watch"
        assert dto.tags == ("import",)

    def test_retrieval_failure_degrades_to_empty(self):
        class _Boom:
            def search(self, *a, **k):
                raise RuntimeError("store down")

        adapter = PgVectorRemediationRetrievalAdapter(store=_Boom())
        # A cold/broken library must never break triage — it grounds nothing.
        assert adapter.retrieve_grounding(workspace_id=_WS_A, finding_kind="log_watch", query_text="q") == []

    def test_belt_and_suspenders_drops_foreign_workspace_rows(self):
        # Even if the store were mis-filtering (returning a foreign row), the
        # adapter's post-filter drops any row whose workspace_id != ours.
        class _LeakyStore:
            filter_calls: list = []

            def search(self, query, *, k=5, filters=None):
                return [_chunk(workspace_id=_WS_B, title="leaked")]

        adapter = PgVectorRemediationRetrievalAdapter(store=_LeakyStore())
        assert adapter.retrieve_grounding(workspace_id=_WS_A, finding_kind="log_watch", query_text="q") == []
