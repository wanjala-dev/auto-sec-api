"""Canonical enums for the Shared Platform bounded context."""

from __future__ import annotations

from enum import Enum


class FileType(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"
    OTHER = "other"


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
