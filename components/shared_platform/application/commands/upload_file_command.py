"""Command and result value objects for file upload processing."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UploadFileCommand:
    owner_id: UUID
    workspace_id: str
    content_type: str
    # Indexing is OPT-IN: only uploads that explicitly ask (e.g. the
    # AI-grounding uploader) enter the embed pipeline. Everything else
    # lands not_indexed until a user clicks Index.
    request_indexing: bool = False
    # Timestamp for index-quota accounting when request_indexing is set;
    # populated by the controller (application stays framework-free).
    now: object = None
    # file_obj is passed separately to the use case (not serializable)


@dataclass(frozen=True)
class UploadFileResult:
    file_id: int
    file_type: str
    processing_status: str
    file_url: str
    file_path: str
    created: str  # ISO format
    workspace_id: str
    owner_id: str
    task_id: str | None = None
    # Populated when an index-on-upload request was refused (quota,
    # breaker, unconfigured) — the upload itself still succeeded.
    index_message: str = ""


@dataclass(frozen=True)
class UploadFileFailure:
    message: str
    status_code: int = 400
