"""Resource DTO for the scan-run SBOM endpoint response."""

from __future__ import annotations

from dataclasses import dataclass

from components.container_security.application.use_cases.get_image_sbom_use_case import (
    ImageSbomView,
)


@dataclass(frozen=True)
class ImageSbomResource:
    scan_run_id: str
    image_ref: str
    format: str
    spec_version: str
    size_bytes: int
    package_count: int
    created_at: str | None
    fetch_url: str | None
    download_url: str | None

    @classmethod
    def from_view(cls, view: ImageSbomView) -> ImageSbomResource:
        return cls(
            scan_run_id=str(view.scan_run_id),
            image_ref=view.image_ref,
            format=view.format,
            spec_version=view.spec_version,
            size_bytes=view.size_bytes,
            package_count=view.package_count,
            created_at=view.created_at.isoformat() if view.created_at else None,
            fetch_url=view.fetch_url,
            download_url=view.download_url,
        )

    def to_dict(self) -> dict:
        return {
            "scan_run_id": self.scan_run_id,
            "image_ref": self.image_ref,
            "format": self.format,
            "spec_version": self.spec_version,
            "size_bytes": self.size_bytes,
            "package_count": self.package_count,
            "created_at": self.created_at,
            "fetch_url": self.fetch_url,
            "download_url": self.download_url,
        }
