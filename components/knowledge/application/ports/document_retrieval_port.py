"""Port: retrieve chunks from the UPLOADED-DOCUMENTS store for selected files.

The workspace has two indexed corpora:

* the workspace SNAPSHOT (``ai_embedding_chunks``, ``source=workspace_snapshot``)
  — reached via ``WorkspaceRetrievalPort``;
* the UPLOADED DOCUMENTS (PDF/docx chunks embedded on upload) — reached
  via THIS port.

This port exists so grounded generation can target the documents the
author explicitly SELECTED for a draft ("ground on last quarter's
report") instead of hoping relevance ranking surfaces them. Selection
is the contract: ``file_ids`` is mandatory, and the adapter must pin
results to ``workspace_id`` so a file id from another workspace simply
matches nothing (tenancy is enforced by the metadata filter itself).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.knowledge.application.ports.vector_store_port import (
    RetrievedChunk,
)


class DocumentRetrievalPort(ABC):
    """RAG read path over the uploaded-documents corpus, per selected files."""

    @abstractmethod
    def search(
        self,
        *,
        workspace_id: str,
        query: str,
        file_ids: list[str],
        k: int = 6,
    ) -> list[RetrievedChunk]:
        """Return up to *k* chunks from the SELECTED files ranked by
        relevance to *query*.

        An empty ``file_ids`` list returns ``[]`` — no selection means no
        document grounding, never "all documents". An empty result means
        the selected files have nothing relevant indexed — callers surface
        that honestly instead of fabricating.
        """
        ...
