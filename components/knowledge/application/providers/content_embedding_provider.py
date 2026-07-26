"""Published seam for knowledge's content-embedding Celery tasks.

The knowledge context owns content embedding/indexing. Other contexts that need
to (re)build embeddings — the workspace post-save reindex, the agents ops CLI —
reach the tasks through this application-layer provider instead of importing
``knowledge.infrastructure.tasks.embedding_tasks`` directly (cross-context
infrastructure imports are forbidden; ADR 0004 infra-boundary series).

Both the synchronous (``run_*``) and enqueued (``enqueue_*``) forms are exposed
so callers pick without ever touching the Celery task object across the boundary.
"""

from __future__ import annotations

from typing import Any


class ContentEmbeddingProvider:
    """Driving-side facade over knowledge's content-embedding tasks."""

    def enqueue_workspace_embedding(self, workspace_id: Any, *, force: bool = False) -> Any:
        """Enqueue a single workspace's embedding refresh (post-save reindex)."""
        from components.knowledge.infrastructure.tasks.embedding_tasks import (
            create_embeddings_for_workspace,
        )

        return create_embeddings_for_workspace.delay(str(workspace_id), force)

    def run_recent_content(self) -> Any:
        """Run the recent-content embedding pass synchronously."""
        from components.knowledge.infrastructure.tasks.embedding_tasks import (
            create_embeddings_for_workspace_content,
        )

        return create_embeddings_for_workspace_content()

    def enqueue_recent_content(self) -> Any:
        """Enqueue the recent-content embedding pass."""
        from components.knowledge.infrastructure.tasks.embedding_tasks import (
            create_embeddings_for_workspace_content,
        )

        return create_embeddings_for_workspace_content.delay()

    def run_all_content(self) -> Any:
        """Run the full-content embedding pass synchronously."""
        from components.knowledge.infrastructure.tasks.embedding_tasks import (
            create_embeddings_for_all_content,
        )

        return create_embeddings_for_all_content()

    def enqueue_all_content(self) -> Any:
        """Enqueue the full-content embedding pass."""
        from components.knowledge.infrastructure.tasks.embedding_tasks import (
            create_embeddings_for_all_content,
        )

        return create_embeddings_for_all_content.delay()


_default = ContentEmbeddingProvider()


def get_content_embedding_provider() -> ContentEmbeddingProvider:
    """Return the default provider — the published seam for knowledge's embedding tasks."""
    return _default
