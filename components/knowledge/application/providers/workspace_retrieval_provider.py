"""Composition root for the workspace retrieval port."""

from __future__ import annotations

from components.knowledge.application.ports.workspace_retrieval_port import (
    WorkspaceRetrievalPort,
)


def workspace_retrieval() -> WorkspaceRetrievalPort:
    """Return the default ``WorkspaceRetrievalPort`` (pgvector-backed)."""
    from components.knowledge.infrastructure.adapters.pgvector_workspace_retrieval_adapter import (
        PgVectorWorkspaceRetrievalAdapter,
    )

    return PgVectorWorkspaceRetrievalAdapter()
