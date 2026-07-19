"""Request DTO for POST /knowledge/embeddings/similarity/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SimilaritySearchRequest:
    """Input DTO for POST /knowledge/embeddings/similarity/ endpoint.

    Performs similarity search using embeddings.
    """
    query: str
    k: int = 10
    provider: str | None = None
    threshold: float | None = None
    metadata_filter: dict[str, Any] = field(default_factory=dict)
