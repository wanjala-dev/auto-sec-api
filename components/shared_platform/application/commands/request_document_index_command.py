"""Command + result DTOs for the explicit document-index request."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RequestDocumentIndexCommand:
    file_id: int
    requested_by_id: UUID
    workspace_id: str
    now: datetime.datetime


@dataclass(frozen=True)
class RequestDocumentIndexResult:
    file_id: int
    processing_status: str
    dispatched: bool
    task_id: str | None
    detail: str = ""


@dataclass(frozen=True)
class RequestDocumentIndexFailure:
    message: str
    status_code: int
    code: str = ""
