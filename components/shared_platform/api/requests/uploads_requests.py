"""Request DTOs for Uploads (file management) endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CreateFileUploadRequest:
    """Input DTO for POST /uploads/ endpoint (multipart form)."""
    file: bytes
    workspace_id: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None


@dataclass(frozen=True)
class UpdateFileUploadRequest:
    """Input DTO for PUT/PATCH /uploads/{id}/ endpoints."""
    file_name: Optional[str] = None
    description: Optional[str] = None
    workspace_id: Optional[str] = None


@dataclass(frozen=True)
class DeleteFileUploadRequest:
    """Input DTO for DELETE /uploads/{id}/ endpoint."""
    file_id: int
