"""File upload domain entity — framework-free, immutable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class FileEntity:
    id: int
    owner_id: UUID
    workspace_id: str | None
    file_path: str
    file_type: str  # image, pdf, document, other
    processing_status: str  # pending, processing, completed, failed
    processing_error: str | None
    processed_at: datetime | None
    created: datetime
