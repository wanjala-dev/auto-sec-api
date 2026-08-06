"""SbomStorePort — how the core persists + retrieves an image SBOM.

Shaped to the Application Core's need (store this scan's SBOM; find a scan's SBOM;
give me a browser-followable URL), NOT to boto3/MinIO or the ORM — the adapter owns
those. One port covers both the object store and the reference record because the
core's unit of work is "the SBOM" (body + ref) — splitting them would leak the
storage topology into the application layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class StoredSbom:
    """The reference record of a stored SBOM (never the body — that stays in the store)."""

    scan_run_id: UUID
    workspace_id: UUID
    image_ref: str
    format: str  # "cyclonedx"
    spec_version: str  # CycloneDX specVersion, e.g. "1.6"
    bucket: str
    object_key: str
    size_bytes: int
    package_count: int
    created_at: datetime | None = None


class SbomStorePort(ABC):
    @abstractmethod
    def store(self, *, workspace_id: UUID, scan_run_id: UUID, image_ref: str, content: str) -> StoredSbom:
        """Persist the SBOM body + its reference record; idempotent per scan run."""

    @abstractmethod
    def find_for_scan(self, *, workspace_id: UUID, scan_run_id: UUID) -> StoredSbom | None:
        """The stored SBOM for a scan run, or None (the honest absent state)."""

    @abstractmethod
    def presigned_url(self, *, sbom: StoredSbom, download_filename: str | None = None) -> str | None:
        """A time-limited browser-followable GET URL (attachment when a filename is given)."""
