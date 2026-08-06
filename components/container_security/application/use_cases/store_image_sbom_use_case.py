"""Persist the CycloneDX SBOM a completed Trivy scan produced (task #99 P1).

The pillar's post-ingest step: given the completed run's identifiers and its
``ScanResult``, find the ``sbom.cyclonedx`` artifact and store it (object store +
reference row) through the ``SbomStorePort``. Framework-free — the Celery seam
hands in primitives, the port hides MinIO/ORM.

SBOM POLICY (decided, documented): SBOM persistence is best-effort relative to the
scan — the scan already COMPLETED and its findings are the truth. An absent artifact
is an honest, logged no-op (the engine's SBOM pass failed); a storage error raises
and is caught + logged by the choreography's best-effort hook wrapper. Neither ever
fails the vuln scan.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.container_security.application.ports.sbom_store_port import (
    SbomStorePort,
    StoredSbom,
)
from components.shared_kernel.application.ports.scanner_port import ScanResult

logger = logging.getLogger(__name__)

SBOM_ARTIFACT_KIND = "sbom.cyclonedx"


class StoreImageSbomUseCase:
    def __init__(self, sbom_store: SbomStorePort):
        self._store = sbom_store

    def execute(
        self,
        *,
        run_id: UUID,
        workspace_id: UUID,
        target_ref: str,
        result: ScanResult,
    ) -> StoredSbom | None:
        artifact = next((a for a in result.artifacts if a.kind == SBOM_ARTIFACT_KIND), None)
        if artifact is None:
            logger.info("image_sbom_absent run_id=%s target=%s (no SBOM artifact on result)", run_id, target_ref)
            return None
        stored = self._store.store(
            workspace_id=workspace_id,
            scan_run_id=run_id,
            image_ref=target_ref,
            content=artifact.content,
        )
        logger.info(
            "image_sbom_stored run_id=%s target=%s key=%s bytes=%s packages=%s",
            run_id,
            target_ref,
            stored.object_key,
            stored.size_bytes,
            stored.package_count,
        )
        return stored
