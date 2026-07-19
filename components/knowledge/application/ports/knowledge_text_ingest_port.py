"""Port: ingest an arbitrary text corpus into the knowledge vector store.

Separate from the document-upload path (which reads files from disk) —
this port takes text that's already in memory (e.g. a generated report
body) along with a stable ``document_key`` so regeneration can
overwrite the prior chunks in place.

Implementations chunk, embed, and write to whatever vector backend the
workspace's knowledge store uses. Both the chunker and the embedding
model are adapter concerns; callers see only ``index_text``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class KnowledgeTextIngestPort(ABC):
    @abstractmethod
    def index_text(
        self,
        *,
        text: str,
        document_key: str,
        metadata: dict,
    ) -> int:
        """Chunk *text*, embed every chunk, and write to the vector store.

        ``document_key`` must be stable across re-indexes for the same
        logical document — the adapter uses it to derive deterministic
        chunk ids so repeat calls replace prior chunks in place.

        Returns the number of chunks written. Raises if the backend is
        unavailable or the corpus is empty; callers decide whether to
        retry or log and move on.
        """
        ...

    @abstractmethod
    def delete_by_key(self, *, document_key: str) -> int:
        """Remove all chunks previously indexed under *document_key*.

        Returns the chunk count removed. No-op (returns ``0``) when
        nothing matches.
        """
        ...
