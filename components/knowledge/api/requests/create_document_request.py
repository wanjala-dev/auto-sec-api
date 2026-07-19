"""Request DTO for POST /knowledge/vector_stores/documents/create/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateDocumentRequest:
    """Input DTO for POST /knowledge/vector_stores/documents/create/ endpoint.

    Creates a document in the vector store for retrieval.
    """
    content: str
    workspace_id: str | None = None
    document_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
