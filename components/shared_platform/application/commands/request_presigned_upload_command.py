"""Command + result DTOs for the request-presigned-upload use case."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RequestPresignedUploadCommand:
    """Caller wants a presigned PUT URL so the browser can upload
    ``filename`` (of MIME type ``content_type``) directly to S3.

    The use case decides the storage key, allocates a ``File`` row,
    and returns the signed URL plus the file id (for downstream M2M
    relationships such as ``Recipient.multimedia``).
    """

    owner_id: UUID
    workspace_id: str
    filename: str
    content_type: str


@dataclass(frozen=True)
class PresignedUploadResult:
    file_id: int
    key: str
    put_url: str
    expires_in: int


@dataclass(frozen=True)
class PresignedUploadFailure:
    message: str
    status_code: int
