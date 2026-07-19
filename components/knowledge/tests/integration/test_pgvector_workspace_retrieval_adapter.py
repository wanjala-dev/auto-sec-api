"""Integration tests for the workspace retrieval adapter.

Covers the empty-store, populated-store, and cross-workspace isolation
cases.  Embedding calls are stubbed — the SQL path still runs.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from components.knowledge.application.providers.workspace_retrieval_provider import (
    workspace_retrieval,
)


class _FakeEmbeddings:
    """Returns a deterministic pseudo-vector; signature matches LangChain."""

    def embed_documents(self, texts):
        return [[0.0] * 1536 for _ in texts]

    def embed_query(self, text):
        return [0.0] * 1536


@pytest.fixture
def _stub_embeddings():
    factory_target = (
        "components.knowledge.infrastructure.factories.embeddings.factory."
        "EmbeddingsFactory.create_embeddings"
    )
    with patch(factory_target, return_value=_FakeEmbeddings()):
        yield


@pytest.mark.django_db
class TestPgVectorWorkspaceRetrievalAdapter:
    def test_empty_store_returns_empty_list(self, _stub_embeddings):
        retriever = workspace_retrieval()
        result = retriever.search(
            workspace_id="00000000-0000-0000-0000-000000000000",
            query="tldr",
            k=5,
        )
        assert result == []

    def test_blank_query_returns_empty_list(self, _stub_embeddings):
        retriever = workspace_retrieval()
        assert retriever.search(workspace_id="ws-1", query="", k=5) == []
        assert retriever.search(workspace_id="ws-1", query="   ", k=5) == []

    def test_missing_workspace_id_returns_empty_list(self, _stub_embeddings):
        retriever = workspace_retrieval()
        assert retriever.search(workspace_id="", query="tldr", k=5) == []

    def test_degrades_to_empty_when_pgvector_unavailable(
        self, workspace_factory, _stub_embeddings
    ):
        """pytest skips migrations so CREATE EXTENSION vector never runs.

        The adapter must notice and return an empty list rather than
        raising a ProgrammingError — that's the contract the deep
        planner and the retrieval tool rely on.
        """
        from components.knowledge.application.providers.workspace_index_provider import (
            workspace_index,
        )

        workspace = workspace_factory(
            workspace_name="Grounded Org",
            workspace_story="We fund early-childhood literacy.",
        )
        workspace_index().reindex(str(workspace.id))

        result = workspace_retrieval().search(
            workspace_id=str(workspace.id),
            query="mission",
            k=5,
        )
        assert result == []

    def test_forwards_scoped_filter_when_extension_available(self):
        """When pgvector IS available, the adapter should delegate with
        the correct workspace + source filter.

        Covered via mock so the test doesn't require the extension.
        """
        from unittest.mock import patch

        from components.knowledge.application.ports.vector_store_port import (
            RetrievedChunk,
        )
        from components.knowledge.infrastructure.adapters.pgvector_workspace_retrieval_adapter import (
            PgVectorWorkspaceRetrievalAdapter,
        )

        adapter = PgVectorWorkspaceRetrievalAdapter()
        with patch.object(
            PgVectorWorkspaceRetrievalAdapter, "_pgvector_available", return_value=True
        ), patch(
            # Tier 3 #11 — adapter delegates to hybrid_search_rrf now,
            # not the pure-vector ``search``.  Filters + k contract is
            # unchanged.
            "components.knowledge.infrastructure.adapters.vector_store."
            "pgvector_store_adapter.PgVectorStoreAdapter.hybrid_search_rrf"
        ) as mock_search:
            mock_search.return_value = [
                RetrievedChunk(
                    content="Mission.",
                    metadata={"workspace_id": "ws-1", "source": "workspace_snapshot"},
                    score=0.9,
                )
            ]
            result = adapter.search(workspace_id="ws-1", query="mission", k=3)

        # SEE-199 — with no viewer_role the adapter forwards the
        # least-privilege sensitivity filter (GENERAL only) alongside the
        # workspace + source pins.
        mock_search.assert_called_once_with(
            "mission",
            k=3,
            filters={
                "workspace_id": "ws-1",
                "source": "workspace_snapshot",
                "sensitivity": ["general"],
            },
        )
        assert len(result) == 1
