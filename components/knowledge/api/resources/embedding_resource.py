"""Response DTO for embedding endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EmbeddingResource:
    """A single embedding vector."""
    text: str
    embedding: list[float] = field(default_factory=list)
    model: str | None = None
    dimensions: int = 0


@dataclass(frozen=True)
class EmbeddingCollectionResource:
    """Output DTO for batch embedding endpoints."""
    embeddings: list[EmbeddingResource] = field(default_factory=list)
    model: str | None = None
    total: int = 0


@dataclass(frozen=True)
class SimilarityMatchResource:
    """A single similarity match result."""
    document_id: str | None = None
    content: str | None = None
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimilaritySearchResource:
    """Output DTO for similarity search endpoints."""
    query: str
    matches: list[SimilarityMatchResource] = field(default_factory=list)
    total: int = 0
