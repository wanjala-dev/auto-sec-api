"""Composition root: build the ``CorpusChunkIndexPort`` adapter.

Providers are the sanctioned place to wire an ORM-backed adapter to a port
(architecture-manifesto Rule 9). Consumers in OTHER contexts resolve the write
door through this provider — never by importing the knowledge adapter directly
(that would be a cross-context infrastructure import).
"""

from __future__ import annotations

from components.knowledge.application.ports.corpus_chunk_index_port import (
    CorpusChunkIndexPort,
)


def build_corpus_chunk_index_port() -> CorpusChunkIndexPort:
    from components.knowledge.infrastructure.adapters.pgvector_corpus_chunk_index_adapter import (
        PgVectorCorpusChunkIndexAdapter,
    )

    return PgVectorCorpusChunkIndexAdapter()
