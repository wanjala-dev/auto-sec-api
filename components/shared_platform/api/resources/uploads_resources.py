"""Resource DTOs for Uploads (file management) entities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FileUploadResource:
    """Output DTO for file upload detail endpoints."""
    id: int
    file_name: str
    file_url: str
    file_path: str
    file_type: str
    file_size: int
    processing_status: str
    workspace_id: str
    owner_id: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class FileUploadCollectionResource:
    """Output DTO for file upload list endpoints."""
    items: list[FileUploadResource]
    count: int = 0
