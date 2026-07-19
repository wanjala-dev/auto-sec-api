"""Pure domain entities for knowledge documents and chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class DocumentEntity:
    id: UUID
    title: str
    content: str
    source: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class DocumentChunkEntity:
    id: UUID
    document_id: UUID
    content: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None
