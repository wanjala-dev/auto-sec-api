"""Port: index a single keyed chunk into the ``ai_embedding_chunks`` store.

The ``knowledge`` context OWNS ``ai_embedding_chunks`` (the pgvector RAG store that
``PgVectorStoreAdapter`` / the workspace-retrieval adapter read). Other contexts
that need to make their own records retrievable through that store MUST go through
this application port rather than writing the ``EmbeddingChunk`` ORM model
themselves — writing another context's persistence is a C2 violation
(architecture skill). Knowledge is the sole writer of its store; this port is the
sanctioned door.

Contract:
- ``index_chunk`` embeds *content* (reusing knowledge's own embeddings stack) and
  writes ONE ``EmbeddingChunk`` row carrying *metadata* plus the ``document_key``.
  It is idempotent: a repeat call for the same ``document_key`` replaces the prior
  row in place (delete-by-key then insert), so re-embedding updates, never
  duplicates.
- ``delete_by_key`` removes the chunk(s) previously written under *document_key*
  (the revocation door — e.g. when a source record is withdrawn).

Callers pass raw *content* + a metadata dict; both the embedding model and the
vector column are adapter concerns. The metadata is the retrieval filter surface
(e.g. ``{"chunk_type": ..., "workspace_id": ...}``) — callers stamp whatever
predicates their retrieval will filter on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CorpusChunkIndexPort(ABC):
    @abstractmethod
    def index_chunk(self, *, document_key: str, content: str, metadata: dict) -> int:
        """Embed *content* and write it as one keyed chunk into the store.

        ``document_key`` is stable per logical record; a repeat call replaces the
        prior chunk in place. Returns the number of chunks written (0 when
        *content* is empty). A best-effort embedding failure does NOT raise — the
        row is still written so it stays metadata/keyword-retrievable; it raises
        only on a genuine store-write failure.
        """
        ...

    @abstractmethod
    def delete_by_key(self, *, document_key: str) -> int:
        """Remove all chunks previously written under *document_key*. Returns the
        count removed (0 when nothing matches)."""
        ...
