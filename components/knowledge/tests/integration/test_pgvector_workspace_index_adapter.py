"""Integration test for the workspace index pipeline end-to-end.

Stubs the embedding provider (no OpenAI calls) but exercises the real
Workspace ORM, the Django data adapter, the pgvector adapter's
transactional replace-chunks path, and the ``EmbeddingChunk`` table.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from components.knowledge.application.providers.workspace_index_provider import (
    workspace_index,
)
from components.knowledge.domain.value_objects.workspace_snapshot import (
    ReindexResult,
)


class _FakeEmbeddings:
    """Deterministic stand-in for a LangChain embeddings client."""

    def __init__(self, dimension: int = 1536):
        self._dimension = dimension

    def embed_documents(self, texts):
        return [self._vector_for(text) for text in texts]

    def embed_query(self, text):
        return self._vector_for(text)

    def _vector_for(self, text: str) -> list[float]:
        # Stable pseudo-vector: uses character codepoints mod 1.0 so chunks
        # get slightly different vectors without ever hitting the network.
        base = [((ord(c) % 17) / 17.0) for c in text[: self._dimension]]
        if len(base) < self._dimension:
            base.extend([0.0] * (self._dimension - len(base)))
        return base[: self._dimension]


@pytest.fixture
def _stub_embeddings():
    fake = _FakeEmbeddings()
    target = "components.knowledge.infrastructure.factories.embeddings.factory.EmbeddingsFactory.create_embeddings"
    with patch(target, return_value=fake):
        yield fake


@pytest.mark.django_db
class TestPgVectorWorkspaceIndexAdapter:
    def test_reindex_unknown_workspace_fails_cleanly(self, _stub_embeddings):
        adapter = workspace_index()
        result = adapter.reindex("00000000-0000-0000-0000-000000000000")
        assert result.status == ReindexResult.STATUS_FAILED
        assert "not found" in result.reason

    def test_reindex_writes_chunks(self, workspace_factory, _stub_embeddings):
        from infrastructure.persistence.ai.models import EmbeddingChunk

        workspace = workspace_factory(
            workspace_name="Wanjala Foundation",
            workspace_story="We fund literacy programs across East Africa.",
            mission="Place books in every rural school.",
        )
        adapter = workspace_index()
        # The Workspace.post_save reindex signal (run eagerly by Celery in tests)
        # already indexed this workspace on creation. Clear those chunks so the
        # explicit reindex below exercises a from-scratch index, not a no-op skip.
        adapter.delete(str(workspace.id))

        result = adapter.reindex(str(workspace.id))

        assert result.status == ReindexResult.STATUS_INDEXED
        assert result.chunks_written >= 2
        assert result.content_hash

        chunks = EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(workspace.id),
            metadata__source="workspace_snapshot",
        )
        assert chunks.count() == result.chunks_written
        assert {c.metadata["section"] for c in chunks} >= {"identity", "mission"}
        assert all(c.metadata["content_hash"] == result.content_hash for c in chunks)

    def test_reindex_twice_skips_when_hash_unchanged(self, workspace_factory, _stub_embeddings):
        workspace = workspace_factory(
            workspace_name="Wanjala Foundation",
            workspace_story="Stable story.",
        )
        adapter = workspace_index()
        # Clear chunks auto-written by the post_save reindex signal (see above).
        adapter.delete(str(workspace.id))

        first = adapter.reindex(str(workspace.id))
        assert first.status == ReindexResult.STATUS_INDEXED

        second = adapter.reindex(str(workspace.id))
        assert second.status == ReindexResult.STATUS_SKIPPED
        assert second.content_hash == first.content_hash

    def test_force_reindex_rewrites_chunks_even_when_hash_unchanged(self, workspace_factory, _stub_embeddings):
        from infrastructure.persistence.ai.models import EmbeddingChunk

        workspace = workspace_factory(
            workspace_name="Wanjala Foundation",
            workspace_story="Stable story.",
        )
        adapter = workspace_index()

        adapter.reindex(str(workspace.id))
        original_ids = set(
            EmbeddingChunk.objects.filter(metadata__workspace_id=str(workspace.id)).values_list("id", flat=True)
        )

        result = adapter.reindex(str(workspace.id), force=True)

        assert result.status == ReindexResult.STATUS_INDEXED
        new_ids = set(
            EmbeddingChunk.objects.filter(metadata__workspace_id=str(workspace.id)).values_list("id", flat=True)
        )
        assert new_ids.isdisjoint(original_ids)

    def test_reindex_replaces_chunks_when_content_changes(self, workspace_factory, _stub_embeddings):
        from infrastructure.persistence.ai.models import EmbeddingChunk

        workspace = workspace_factory(
            workspace_name="Wanjala Foundation",
            workspace_story="Original story.",
        )
        adapter = workspace_index()
        # Clear chunks auto-written by the post_save reindex signal (see above).
        adapter.delete(str(workspace.id))
        adapter.reindex(str(workspace.id))
        first_hash = (
            EmbeddingChunk.objects.filter(metadata__workspace_id=str(workspace.id)).first().metadata["content_hash"]
        )

        workspace.workspace_story = "A completely new story about literacy."
        workspace.save()
        # The save above re-fires the reindex signal; clear so the explicit
        # reindex below is what writes the new-content chunks under test.
        adapter.delete(str(workspace.id))

        result = adapter.reindex(str(workspace.id))
        assert result.status == ReindexResult.STATUS_INDEXED
        new_hashes = {
            c.metadata["content_hash"] for c in EmbeddingChunk.objects.filter(metadata__workspace_id=str(workspace.id))
        }
        assert new_hashes == {result.content_hash}
        assert result.content_hash != first_hash

    def test_reindex_repairs_chunks_whose_embedding_is_missing(self, workspace_factory, _stub_embeddings):
        """A matching content hash is NOT proof the workspace is indexed.

        The bug: the skip read the newest chunk's ``content_hash`` and nothing
        else, so rows with ``embedding IS NULL`` were reported SKIPPED
        ("content hash unchanged") and never repaired. On 2026-08-19 that left
        39 NULL-embedding rows in the pooled database that only ``--force``
        could clear — meaning a future NULL-embedding incident would not
        self-heal, and the reindex would keep reporting success while doing
        nothing. A chunk with no vector is invisible to vector search: RAG
        returns zero hits and raises nothing.

        ``_embeddings_expected`` is patched rather than the write path's
        ``_pgvector_available``: this suite runs on SQLite, where
        ``_attach_vectors`` deliberately writes no vector and a NULL embedding
        proves nothing. Patching it says "pretend this backend stores vectors",
        which is the production condition under test. The write path keeps its
        own unpatched probe, so no ``::vector`` SQL is attempted here.
        """
        from infrastructure.persistence.ai.models import EmbeddingChunk

        workspace = workspace_factory(
            workspace_name="Wanjala Foundation",
            workspace_story="Stable story.",
        )
        adapter = workspace_index()
        adapter.delete(str(workspace.id))

        first = adapter.reindex(str(workspace.id))
        assert first.status == ReindexResult.STATUS_INDEXED
        # The chunks exist, carry the right hash — and have no embedding.
        assert EmbeddingChunk.objects.filter(metadata__workspace_id=str(workspace.id), embedding__isnull=True).exists()

        target = (
            "components.knowledge.infrastructure.adapters."
            "pgvector_workspace_index_adapter.PgVectorWorkspaceIndexAdapter."
            "_embeddings_expected"
        )
        with patch(target, return_value=True):
            second = adapter.reindex(str(workspace.id))

        assert second.status == ReindexResult.STATUS_INDEXED, (
            "a NULL-embedding chunk was skipped because its hash matched — the "
            "index reports healthy and returns nothing"
        )
        assert second.content_hash == first.content_hash

    def test_the_vector_write_targets_the_same_connection_as_the_rows(self, workspace_factory, _stub_embeddings):
        """The raw ``UPDATE ... SET embedding`` must follow the router.

        ``from django.db import connection`` is the ``default`` connection —
        always, whatever tenant is bound. The ORM inserts route through
        ``TenantRouter`` to the tenant's database; this raw cursor did not
        follow them, so on a dedicated tenant the UPDATE ran against
        ``default`` where those UUIDs do not exist: zero rows matched, no
        error, NULL embeddings. It cost a real OpenAI call and reported
        ``indexed``.

        Invisible on the pool, where alias and connection coincide — so the
        assertion has to be on the ALIAS the write was issued against, not on
        the result.
        """
        workspace = workspace_factory(workspace_name="Wanjala Foundation", workspace_story="Stable story.")
        adapter = workspace_index()
        adapter.delete(str(workspace.id))

        seen: list[str] = []
        real = adapter._attach_vectors

        def _spy(created_rows, vectors, *, using):
            seen.append(using)
            return real(created_rows, vectors, using=using)

        with patch.object(adapter, "_attach_vectors", _spy):
            assert adapter.reindex(str(workspace.id)).status == ReindexResult.STATUS_INDEXED

        from components.shared_kernel.application.transactional import db_alias_for
        from infrastructure.persistence.ai.models import EmbeddingChunk

        assert seen == [db_alias_for(EmbeddingChunk)], (
            "the vector write was issued against a different connection than "
            "the rows were inserted on — it will match zero rows and say nothing"
        )

    def test_reindex_does_not_skip_a_half_replaced_chunk_set(self, workspace_factory, _stub_embeddings):
        """Mixed hashes are not an index either.

        Reading only the newest row could not see this: if the newest chunk
        happened to carry the current hash, a partially-written set was
        accepted as complete.
        """
        from infrastructure.persistence.ai.models import EmbeddingChunk

        workspace = workspace_factory(
            workspace_name="Wanjala Foundation",
            workspace_story="Stable story.",
            mission="Books everywhere.",
        )
        adapter = workspace_index()
        adapter.delete(str(workspace.id))
        first = adapter.reindex(str(workspace.id))
        assert first.status == ReindexResult.STATUS_INDEXED

        stale = EmbeddingChunk.objects.filter(metadata__workspace_id=str(workspace.id)).order_by("created_at").first()
        stale.metadata = {**stale.metadata, "content_hash": "stale-hash"}
        stale.save(update_fields=["metadata"])

        assert adapter.reindex(str(workspace.id)).status == ReindexResult.STATUS_INDEXED

    def test_delete_removes_only_this_workspaces_chunks(self, workspace_factory, _stub_embeddings):
        from infrastructure.persistence.ai.models import EmbeddingChunk

        ws_a = workspace_factory(workspace_name="Wanjala Foundation", workspace_story="Story A.")
        ws_b = workspace_factory(workspace_name="Other Foundation", workspace_story="Story B.")
        adapter = workspace_index()
        adapter.reindex(str(ws_a.id))
        adapter.reindex(str(ws_b.id))

        deleted = adapter.delete(str(ws_a.id))
        assert deleted > 0

        assert not EmbeddingChunk.objects.filter(metadata__workspace_id=str(ws_a.id)).exists()
        assert EmbeddingChunk.objects.filter(metadata__workspace_id=str(ws_b.id)).exists()
