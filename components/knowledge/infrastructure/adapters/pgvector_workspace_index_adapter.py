"""pgvector adapter that indexes a workspace's snapshot for retrieval.

Flow:
    1. Load facts via ``WorkspaceSnapshotDataPort``.
    2. Build a ``WorkspaceSnapshot`` (pure domain).
    3. If the snapshot is empty → return STATUS_EMPTY.
    4. Compare the new ``content_hash`` to the hash stored on the workspace's
       existing chunks.  If identical and ``force`` is false → STATUS_SKIPPED.
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
from typing import Iterable

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
    WorkspaceSnapshotSection,
)

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

        if not force and self._current_hash(workspace_id) == snapshot.content_hash:
            return ReindexResult(
                status=ReindexResult.STATUS_SKIPPED,
                workspace_id=workspace_id,
                content_hash=snapshot.content_hash,
                reason="content hash unchanged",
            )

        try:
            chunks_written = self._replace_chunks(snapshot, workspace_name=data.workspace_name)
        except Exception as exc:
            logger.exception(
                "Failed to reindex workspace %s", workspace_id
            )
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

    def _current_hash(self, workspace_id: str) -> str | None:
        from infrastructure.persistence.ai.models import EmbeddingChunk

        row = (
            EmbeddingChunk.objects
            .filter(
                metadata__workspace_id=str(workspace_id),
                metadata__source=CHUNK_SOURCE,
            )
            .values("metadata")
            .order_by("-created_at")
            .first()
        )
        if not row:
            return None
        return (row.get("metadata") or {}).get("content_hash")

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

        texts = [
            render_section_for_embedding(workspace_name, section)
            for section in snapshot.sections
        ]

        embeddings_client = EmbeddingsFactory.create_embeddings(
            provider=self._embeddings_provider
        )
        vectors: list[list[float]] = embeddings_client.embed_documents(texts)
        if len(vectors) != len(snapshot.sections):
            raise RuntimeError(
                f"embedding count mismatch: got {len(vectors)} for "
                f"{len(snapshot.sections)} sections"
            )

        with transaction.atomic():
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
            self._attach_vectors(created, vectors)

        return len(created)

    @staticmethod
    def _attach_vectors(
        created_rows: Iterable, vectors: list[list[float]]
    ) -> None:
        """Write the raw pgvector column.  Django can't bind ``vector`` natively.

        Guarded by a pgvector-availability probe so the adapter stays
        testable in environments where the extension hasn't been created
        — pytest skips migrations, so the ``CREATE EXTENSION vector``
        step never runs on the test DB.  In those environments we index
        chunks without embeddings; retrieval is broken but indexing
        behaviour (replace / skip / delete) is still covered.
        """
        from django.db import connection

        if not PgVectorWorkspaceIndexAdapter._pgvector_available(connection):
            logger.debug(
                "Skipping pgvector write: vector type unavailable on %s backend",
                connection.vendor,
            )
            return

        with connection.cursor() as cursor:
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
            cursor.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1"
            )
            return cursor.fetchone() is not None
