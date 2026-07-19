"""Port: index a workspace into the vector store."""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.knowledge.domain.value_objects.workspace_snapshot import (
    ReindexResult,
)


class WorkspaceIndexPort(ABC):
    """Contract for any backend that indexes workspaces for retrieval.

    Callers hand us a workspace id; we load its facts, build a snapshot,
    and persist embeddings to whatever backend the adapter implements.
    The port is intentionally narrow — all the interesting policy lives
    inside the adapter.
    """

    @abstractmethod
    def reindex(self, workspace_id: str, *, force: bool = False) -> ReindexResult:
        """Build the snapshot for *workspace_id* and write it to the store.

        When ``force`` is false (the default) the adapter may skip the
        write if the snapshot's content hash matches the last indexed
        hash — this is the "don't re-embed on noisy saves" optimisation.
        ``force=True`` always re-embeds; use it from the nightly refresh
        job to heal drift from missed signals.
        """
        ...

    @abstractmethod
    def delete(self, workspace_id: str) -> int:
        """Remove all indexed chunks for *workspace_id*.

        Returns the number of chunks deleted.  Called when a workspace is
        soft-deleted or disabled so retrieval stops returning its
        content.
        """
        ...
