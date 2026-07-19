"""Port: retrieve top-k indexed chunks for a workspace given a natural-language query."""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.knowledge.application.ports.vector_store_port import (
    RetrievedChunk,
)


class WorkspaceRetrievalPort(ABC):
    """Contract for the RAG read path scoped to a single workspace."""

    @abstractmethod
    def search(
        self,
        *,
        workspace_id: str,
        query: str,
        k: int = 5,
        viewer_role: str | None = None,
    ) -> list[RetrievedChunk]:
        """Return up to *k* chunks from *workspace_id* ranked by relevance to *query*.

        *viewer_role* is the effective ``WorkspaceMembership`` role of the actor
        the retrieval runs on behalf of. It scopes results to the sensitivity
        tiers that role may read (see ``domain.value_objects.retrieval_sensitivity``):
        owners/admins read everything; everyone else — and ``None`` — read only
        GENERAL chunks. ``None`` is the least-privilege default, so a caller that
        cannot resolve a role degrades safely rather than leaking restricted facts.

        An empty list means nothing relevant is indexed — callers should
        surface that honestly instead of fabricating an answer.
        """
        ...
