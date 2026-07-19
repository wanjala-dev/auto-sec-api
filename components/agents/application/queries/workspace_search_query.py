"""CQRS query: search workspace content via vector store.

Framework-free — no Django, DRF, or ORM imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from components.knowledge.application.ports.vector_store_port import RetrievedChunk, VectorStorePort


@dataclass(frozen=True)
class WorkspaceSearchRequest:
    """Inbound query parameters for workspace content search."""

    query: str
    workspace_id: str
    k: int = 10


@dataclass(frozen=True)
class WorkspaceSearchResult:
    """Successful search result."""

    query: str
    workspace_id: str
    results: list[dict] = field(default_factory=list)
    total_results: int = 0


class WorkspaceSearchQuery:
    """Read-side query: vector-search across workspace content.

    Delegates to VectorStorePort — no direct factory or SDK access.
    """

    def __init__(self, *, vector_store: VectorStorePort) -> None:
        self._vector_store = vector_store

    def execute(self, request: WorkspaceSearchRequest) -> WorkspaceSearchResult:
        chunks = self._vector_store.search(
            request.query,
            k=request.k,
            filters={"workspace_id": request.workspace_id},
        )

        # Filter to ensure workspace match (defence-in-depth)
        ws_id = str(request.workspace_id)
        matched = [
            c for c in chunks
            if str(c.metadata.get("workspace_id", "")) == ws_id
        ]

        return WorkspaceSearchResult(
            query=request.query,
            workspace_id=request.workspace_id,
            results=[
                {
                    "content": c.content,
                    "metadata": c.metadata,
                    "relevance_score": c.score,
                }
                for c in matched
            ],
            total_results=len(matched),
        )
