"""Tier 3 #14 — port for the per-workspace "latest index" query.

Returns the timestamp of the most recent ``EmbeddingChunk`` written
for a workspace. The SLO compares this against the latest event
time (from ``WorkspaceEventLatestPort``) to compute lag.

Separate from the existing ``WorkspaceIndexPort`` because that port
is about *writing* the index, not reading metadata about it.
Splitting keeps each port small and the adapters single-purpose —
the existing pgvector write adapter doesn't grow a read method just
because the SLO needed one.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class WorkspaceIndexLatestPort(ABC):
    """Resolve the timestamp of the most recent index write for a workspace."""

    @abstractmethod
    def latest_index_time(
        self, *, workspace_id: str
    ) -> Optional[datetime]:
        """Return the most recent ``EmbeddingChunk.created_at`` for
        the workspace, or ``None`` if the workspace has never been
        indexed.

        A freshly-created workspace with no chunks yet returns
        ``None`` — the SLO use case treats that the same way it
        treats a workspace with no events (lag = 0, fully fresh).
        """
        raise NotImplementedError
