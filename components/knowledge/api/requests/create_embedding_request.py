"""Request DTO for POST /knowledge/embeddings/create/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateEmbeddingRequest:
    """Input DTO for POST /knowledge/embeddings/create/ endpoint.

    Creates embeddings for provided text.
    """
    text: str
    model: str | None = None
    provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
