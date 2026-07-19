"""File classification value object — MIME type to file type mapping.

This is pure domain logic: given a content type, determine the file category.
No framework dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical mapping: MIME type → file type
CONTENT_TYPE_MAP: dict[str, str] = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/svg+xml": "image",
    "application/pdf": "pdf",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "text/csv": "document",
    "application/csv": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
}

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(CONTENT_TYPE_MAP.keys())


@dataclass(frozen=True)
class FileClassification:
    """Result of classifying an uploaded file by content type."""

    content_type: str
    file_type: str  # image | pdf | document | other
    is_allowed: bool
    requires_processing: bool  # True for pdf and document


def classify_file(content_type: str) -> FileClassification:
    """Classify a file based on its MIME content type.

    Pure function — no framework dependencies.
    """
    file_type = CONTENT_TYPE_MAP.get(content_type, "other")
    return FileClassification(
        content_type=content_type,
        file_type=file_type,
        is_allowed=content_type in ALLOWED_CONTENT_TYPES,
        requires_processing=file_type in ("pdf", "document"),
    )
