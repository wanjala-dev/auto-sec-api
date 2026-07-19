"""Request DTO for POST /knowledge/vector_stores/search/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchDocumentsRequest:
    """Input DTO for POST /knowledge/vector_stores/search/ endpoint.

    Searches documents in the vector store.
    """
    query: str
    k: int = 5
    workspace_id: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
