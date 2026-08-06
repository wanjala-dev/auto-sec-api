"""Read side: a scan run's SBOM metadata + presigned URLs (task #99 P1).

Returns a framework-free DTO the controller maps to the response. Two presigned
URLs from the same object: ``fetch_url`` (inline — the HUD fetches + renders the
package list client-side, keeping this endpoint's payload light; SBOMs can be MBs)
and ``download_url`` (Content-Disposition: attachment with a stable filename).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.container_security.application.ports.sbom_store_port import SbomStorePort


@dataclass(frozen=True)
class ImageSbomView:
    scan_run_id: UUID
    image_ref: str
    format: str
    spec_version: str
    size_bytes: int
    package_count: int
    created_at: datetime | None
    fetch_url: str | None
    download_url: str | None


class GetImageSbomUseCase:
    def __init__(self, sbom_store: SbomStorePort):
        self._store = sbom_store

    def execute(self, *, workspace_id: UUID, scan_run_id: UUID) -> ImageSbomView | None:
        sbom = self._store.find_for_scan(workspace_id=workspace_id, scan_run_id=scan_run_id)
        if sbom is None:
            return None
        filename = f"sbom-{scan_run_id}.cdx.json"
        return ImageSbomView(
            scan_run_id=sbom.scan_run_id,
            image_ref=sbom.image_ref,
            format=sbom.format,
            spec_version=sbom.spec_version,
            size_bytes=sbom.size_bytes,
            package_count=sbom.package_count,
            created_at=sbom.created_at,
            fetch_url=self._store.presigned_url(sbom=sbom),
            download_url=self._store.presigned_url(sbom=sbom, download_filename=filename),
        )
