"""Composition root for the scan-artifact store (ADR 0022 D2).

Which adapter implements ``ScanArtifactStorePort`` is a policy decision, so it lives in
the application layer (architecture-manifesto Rule 9) — infrastructure implements ports,
it does not choose between them.

One implementation today: the MinIO/S3 object store, which is the same seam in both
environments (MinIO in-cluster locally, real S3 in prod) — so there is nothing to branch
on, only somewhere for a future backend to plug in.
"""

from __future__ import annotations

from components.scanning.application.ports.scan_artifact_store_port import ScanArtifactStorePort


def get_scan_artifact_store() -> ScanArtifactStorePort:
    from components.scanning.infrastructure.adapters.minio_scan_artifact_store import (
        MinioScanArtifactStore,
    )

    return MinioScanArtifactStore()
