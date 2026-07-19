"""Confirm-presigned-upload command + result DTOs (framework-free)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ConfirmPresignedUploadCommand:
    """The browser finished its presigned PUT; optionally kick off indexing."""

    file_id: int
    owner_id: UUID
    # Indexing is OPT-IN (see UploadFileCommand). Confirm-with-index is the
    # grounding uploader's one-round-trip path; the request still runs
    # through the RequestDocumentIndexUseCase policy (quota, breaker).
    request_indexing: bool = False


@dataclass(frozen=True)
class ConfirmPresignedUploadResult:
    file_id: int
    file_type: str
    processing_status: str
    dispatched: bool
    task_id: str | None
    # Populated when an index-on-confirm request was refused (quota,
    # breaker, unconfigured) — the upload itself still succeeded.
    index_message: str = ""


@dataclass(frozen=True)
class ConfirmPresignedUploadFailure:
    message: str
    status_code: int
