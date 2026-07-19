"""Request DTO for POST /knowledge/embeddings/batch/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateEmbeddingsBatchRequest:
    """Input DTO for POST /knowledge/embeddings/batch/ endpoint.

    Creates embeddings for multiple texts in batch.
    """
    texts: list[str] = field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
