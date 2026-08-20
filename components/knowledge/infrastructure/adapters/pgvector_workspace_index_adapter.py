"""pgvector adapter that indexes a workspace's snapshot for retrieval.

Flow:
    1. Load facts via ``WorkspaceSnapshotDataPort``.
    2. Build a ``WorkspaceSnapshot`` (pure domain).
    3. If the snapshot is empty → return STATUS_EMPTY.
    4. Compare the new ``content_hash`` to the hash the workspace is actually
       INDEXED at (see ``_indexed_hash`` — a hash the store cannot back with
       embeddings does not count).  If identical and ``force`` is false →
       STATUS_SKIPPED.
    5. Otherwise: embed every section, wipe the workspace's old chunks, and
       insert fresh ones inside one transaction.

Why wipe-and-replace (vs per-chunk upsert)?  Sections can disappear when a
workspace is edited (e.g. mission text cleared).  A diff-based upsert would
need bookkeeping to delete orphaned sections; wipe-and-replace is cheap at
our chunk counts (≤ ~10 per workspace) and keeps the store honestly in sync
with the current snapshot.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.db import transaction

from components.knowledge.application.ports.workspace_index_port import (
    WorkspaceIndexPort,
)
from components.knowledge.application.ports.workspace_snapshot_data_port import (
    WorkspaceSnapshotDataPort,
)
from components.knowledge.domain.services.workspace_snapshot_builder import (
    build_workspace_snapshot,
    render_section_for_embedding,
)
from components.knowledge.domain.value_objects.injection_scan import (
    is_injection_suspected,
)
from components.knowledge.domain.value_objects.retrieval_sensitivity import (
    sensitivity_for_section,
)
from components.knowledge.domain.value_objects.workspace_snapshot import (
    ReindexResult,
    WorkspaceSnapshot,
)
from components.shared_kernel.application.transactional import db_alias_for

logger = logging.getLogger(__name__)

CHUNK_SOURCE = "workspace_snapshot"


class PgVectorWorkspaceIndexAdapter(WorkspaceIndexPort):
    """Writes workspace snapshot chunks into ``ai_embedding_chunks``."""

    def __init__(
        self,
        *,
        data_port: WorkspaceSnapshotDataPort,
        embeddings_provider: str = "openai",
    ) -> None:
        self._data_port = data_port
        self._embeddings_provider = embeddings_provider

    # ── Public API ───────────────────────────────────────────────────

    def reindex(self, workspace_id: str, *, force: bool = False) -> ReindexResult:
        data = self._data_port.load(workspace_id)
        if data is None:
            return ReindexResult(
                status=ReindexResult.STATUS_FAILED,
                workspace_id=workspace_id,
                reason="workspace not found",
            )

        snapshot = build_workspace_snapshot(data)
        if snapshot.is_empty():
            deleted = self.delete(workspace_id)
            return ReindexResult(
                status=ReindexResult.STATUS_EMPTY,
                workspace_id=workspace_id,
                chunks_written=0,
                content_hash=snapshot.content_hash,
                reason=f"workspace has no indexable content (cleared {deleted} stale chunks)",
            )

        if not force and self._indexed_hash(workspace_id) == snapshot.content_hash:
            return ReindexResult(
                status=ReindexResult.STATUS_SKIPPED,
                workspace_id=workspace_id,
                content_hash=snapshot.content_hash,
                reason="content hash unchanged",
            )

        try:
            chunks_written = self._replace_chunks(snapshot, workspace_name=data.workspace_name)
        except Exception as exc:
            logger.exception("Failed to reindex workspace %s", workspace_id)
            return ReindexResult(
                status=ReindexResult.STATUS_FAILED,
                workspace_id=workspace_id,
                content_hash=snapshot.content_hash,
                reason=str(exc),
            )

        return ReindexResult(
            status=ReindexResult.STATUS_INDEXED,
            workspace_id=workspace_id,
            chunks_written=chunks_written,
            content_hash=snapshot.content_hash,
        )

    def delete(self, workspace_id: str) -> int:
        from infrastructure.persistence.ai.models import EmbeddingChunk

        deleted, _ = EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(workspace_id),
            metadata__source=CHUNK_SOURCE,
        ).delete()
        return int(deleted)

    # ── Internals ────────────────────────────────────────────────────

    def _indexed_hash(self, workspace_id: str) -> str | None:
        """The hash this workspace is ACTUALLY indexed at, or ``None``.

        ``None`` means "there is no usable index here" and the caller must
        re-embed. This used to be ``_current_hash``, which read the newest
        chunk's ``content_hash`` and nothing else — so a matching hash was
        accepted as proof of a working index even when the chunks carried no
        embedding at all.

        That is a silent-success bug with teeth. On 2026-08-19 a backfill left
        39 rows in the pooled database with ``embedding IS NULL``; a plain
        ``reindex_workspaces --all`` reported every one of them SKIPPED
        ("content hash unchanged") and repaired none. Only ``--force`` cleared
        them — which means the next NULL-embedding incident would not
        self-heal, and the reindex would keep reporting success while doing
        nothing. A chunk without a vector is invisible to vector search: the
        workspace's RAG returns zero hits and no error.

        So a skip now requires the stored index to be COMPLETE:

        * at least one chunk exists;
        * every chunk agrees on one hash (a half-replaced set is not an index,
          and reading only the newest row could not see that either);
        * no chunk is missing its embedding — on a backend that stores one.

        The last clause is gated because it must be: the test suite runs on
        SQLite, where ``_attach_vectors`` writes no vector by design, and a
        NULL embedding there is a property of the backend rather than evidence
        of a broken index. It is a SEPARATE method from the write path's probe
        so the two questions — "must a healthy chunk have a vector?" and "can I
        execute a vector UPDATE right now?" — can be answered independently.
        """
        from infrastructure.persistence.ai.models import EmbeddingChunk

        chunks = EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(workspace_id),
            metadata__source=CHUNK_SOURCE,
        )
        hashes = {(row["metadata"] or {}).get("content_hash") for row in chunks.values("metadata")}
        if len(hashes) != 1 or None in hashes:
            return None

        if self._embeddings_expected(db_alias_for(EmbeddingChunk)) and chunks.filter(embedding__isnull=True).exists():
            logger.info(
                "workspace_index_incomplete workspace_id=%s reason=null_embedding — re-embedding "
                "despite an unchanged content hash",
                workspace_id,
            )
            return None

        return hashes.pop()

    @staticmethod
    def _embeddings_expected(using: str) -> bool:
        """Whether a healthy chunk must carry a vector on the *tenant's* backend.

        Takes an alias for the same reason ``_attach_vectors`` does: the bound
        tenant's database is the one the chunks live in, and probing
        ``default`` would answer a question about a different server.
        """
        from django.db import connections

        return PgVectorWorkspaceIndexAdapter._pgvector_available(connections[using])

    def _replace_chunks(
        self,
        snapshot: WorkspaceSnapshot,
        *,
        workspace_name: str,
    ) -> int:
        from components.knowledge.infrastructure.factories.embeddings.factory import (
            EmbeddingsFactory,
        )
        from infrastructure.persistence.ai.models import EmbeddingChunk

        texts = [render_section_for_embedding(workspace_name, section) for section in snapshot.sections]

        embeddings_client = EmbeddingsFactory.create_embeddings(provider=self._embeddings_provider)
        vectors: list[list[float]] = embeddings_client.embed_documents(texts)
        if len(vectors) != len(snapshot.sections):
            raise RuntimeError(f"embedding count mismatch: got {len(vectors)} for {len(snapshot.sections)} sections")

        # The alias the ORM will actually write to under the tenant router.
        # Everything below MUST agree on it — see `_attach_vectors`.
        alias = db_alias_for(EmbeddingChunk)

        with transaction.atomic(using=alias):
            EmbeddingChunk.objects.filter(
                metadata__workspace_id=snapshot.workspace_id,
                metadata__source=CHUNK_SOURCE,
            ).delete()

            new_rows = [
                EmbeddingChunk(
                    content=text,
                    metadata={
                        "source": CHUNK_SOURCE,
                        "workspace_id": snapshot.workspace_id,
                        "section": section.key,
                        "section_title": section.title,
                        "content_hash": snapshot.content_hash,
                        # SEE-199 — role-scoped retrieval tier. Financial /
                        # pipeline sections are owner/admin-only; the reader
                        # filters on this at SQL.
                        "sensitivity": sensitivity_for_section(section.key),
                        # SEE-200 — flag chunks whose text carries
                        # instruction-injection shapes so the planner weights
                        # them with extra suspicion (defence-in-depth behind
                        # the planner's untrusted-content grounding rule).
                        "untrusted": is_injection_suspected(text),
                    },
                )
                for text, section in zip(texts, snapshot.sections)
            ]
            created = EmbeddingChunk.objects.bulk_create(new_rows)
            self._attach_vectors(created, vectors, using=alias)

        return len(created)

    @staticmethod
    def _attach_vectors(created_rows: Iterable, vectors: list[list[float]], *, using: str) -> None:
        """Write the raw pgvector column.  Django can't bind ``vector`` natively.

        ``using`` is REQUIRED, and it is the whole reason this signature
        changed. ``from django.db import connection`` is the ``default``
        connection — always, regardless of which tenant is bound. The ORM
        writes above route through ``TenantRouter`` to the tenant's database;
        this raw cursor did not follow them. So on a dedicated tenant the rows
        were inserted into ``tenant_<name>`` and the ``UPDATE ... SET
        embedding`` ran against ``default``, where those UUIDs do not exist:
        **zero rows matched, no error, chunks left with NULL embeddings.**

        Invisible on the pool, where the alias and the connection happen to be
        the same object — which is why it survived. Caught on 2026-08-19 when
        the first ``--tenant faura`` backfill reported ``indexed (chunks=6)``,
        billed a real OpenAI call, and left 6 of 6 embeddings NULL.

        Guarded by a pgvector-availability probe so the adapter stays
        testable in environments where the extension hasn't been created
        — pytest skips migrations, so the ``CREATE EXTENSION vector``
        step never runs on the test DB.  In those environments we index
        chunks without embeddings; retrieval is broken but indexing
        behaviour (replace / skip / delete) is still covered.
        """
        from django.db import connections

        conn = connections[using]
        if not PgVectorWorkspaceIndexAdapter._pgvector_available(conn):
            logger.debug(
                "Skipping pgvector write: vector type unavailable on %s backend (alias %s)",
                conn.vendor,
                using,
            )
            return

        with conn.cursor() as cursor:
            for row, vector in zip(created_rows, vectors):
                cursor.execute(
                    "UPDATE ai_embedding_chunks SET embedding = %s::vector WHERE id = %s",
                    [str(list(vector)), str(row.id)],
                )

    @staticmethod
    def _pgvector_available(connection) -> bool:
        """Return True iff the current DB is Postgres with pgvector loaded."""
        if connection.vendor != "postgresql":
            return False
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")
            return cursor.fetchone() is not None
