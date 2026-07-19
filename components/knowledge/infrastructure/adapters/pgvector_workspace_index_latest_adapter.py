"""ORM adapter for the ``WorkspaceIndexLatestPort``.

Reads ``EmbeddingChunk.created_at`` for the workspace and returns
the max. Uses the JSON ``metadata->>workspace_id`` filter because
``EmbeddingChunk`` stores workspace scope in metadata, not as a
direct FK column (the table is a generic chunk store shared across
all RAG workloads).

Tier 3 #14. See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from django.db.models import Max

from components.knowledge.application.ports.workspace_index_latest_port import (
    WorkspaceIndexLatestPort,
)

logger = logging.getLogger(__name__)


class PgvectorWorkspaceIndexLatestAdapter(WorkspaceIndexLatestPort):
    """Concrete adapter — one aggregate over ``ai_embedding_chunks``."""

    def latest_index_time(
        self, *, workspace_id: str
    ) -> Optional[datetime]:
        if not workspace_id:
            return None

        try:
            from infrastructure.persistence.ai.models import EmbeddingChunk
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "knowledge: SLO audit failed to import EmbeddingChunk"
            )
            return None

        # ``metadata__workspace_id`` exploits Django's JSONField
        # lookup — it generates the right Postgres ``->>`` operator
        # and is index-friendly when ``metadata`` carries a GIN
        # index on the workspace_id key. The fallback case (no
        # GIN) still works; it just scans more rows.
        return EmbeddingChunk.objects.filter(
            metadata__workspace_id=str(workspace_id)
        ).aggregate(latest=Max("created_at"))["latest"]
