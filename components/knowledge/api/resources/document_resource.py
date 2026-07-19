"""Response DTO for document/vector store endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentChunkResource:
    """A chunk of document content."""
    chunk_id: str | None = None
    content: str = ""
    page_number: int | None = None
    position: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentResource:
    """Output DTO for document detail endpoints."""
    document_id: str
    id: str | None = None
    title: str | None = None
    content: str | None = None
    file_id: str | None = None
    workspace_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    chunks: list[DocumentChunkResource] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentCollectionResource:
    """Output DTO for document list endpoints."""
    documents: list[DocumentResource] = field(default_factory=list)
    total: int = 0
    count: int = 0


@dataclass(frozen=True)
class SearchResultResource:
    """A single search result."""
    document_id: str | None = None
    content: str = ""
    score: float = 0.0
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentSearchResource:
    """Output DTO for document search endpoints."""
    query: str
    results: list[SearchResultResource] = field(default_factory=list)
    total: int = 0
