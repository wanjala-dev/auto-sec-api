"""Composition root for the workspace index pipeline.

Wires the Django data adapter and the pgvector index adapter together and
hands callers a ready-to-use ``WorkspaceIndexPort`` implementation.  This is
a policy decision (which adapter implements which port), so it lives in
the application layer per Explicit Architecture Rule 9.
"""

from __future__ import annotations

from components.knowledge.application.ports.workspace_index_port import (
    WorkspaceIndexPort,
)


def workspace_index(embeddings_provider: str = "openai") -> WorkspaceIndexPort:
    """Return the default ``WorkspaceIndexPort`` (Django + pgvector)."""
    from components.knowledge.infrastructure.adapters.django_workspace_snapshot_data_adapter import (
        DjangoWorkspaceSnapshotDataAdapter,
    )
    from components.knowledge.infrastructure.adapters.pgvector_workspace_index_adapter import (
        PgVectorWorkspaceIndexAdapter,
    )

    return PgVectorWorkspaceIndexAdapter(
        data_port=DjangoWorkspaceSnapshotDataAdapter(),
        embeddings_provider=embeddings_provider,
    )
