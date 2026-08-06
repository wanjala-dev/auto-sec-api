"""Composition root for the image-SBOM seam (ports → adapters wiring).

``build_post_ingest_hook`` is what the scanner registry resolves for
``container_security.trivy`` — the application-layer callable the generic scan
choreography invokes after a completed run (never this context's infrastructure
directly; the cross-context boundary stays application-to-application).
"""

from __future__ import annotations

from components.container_security.application.ports.sbom_store_port import SbomStorePort
from components.container_security.application.use_cases.get_image_sbom_use_case import (
    GetImageSbomUseCase,
)
from components.container_security.application.use_cases.store_image_sbom_use_case import (
    StoreImageSbomUseCase,
)


def build_sbom_store() -> SbomStorePort:
    from components.container_security.infrastructure.adapters.minio_sbom_store import (
        MinioSbomStore,
    )

    return MinioSbomStore()


def build_store_image_sbom_use_case() -> StoreImageSbomUseCase:
    return StoreImageSbomUseCase(sbom_store=build_sbom_store())


def build_get_image_sbom_use_case() -> GetImageSbomUseCase:
    return GetImageSbomUseCase(sbom_store=build_sbom_store())


def build_post_ingest_hook():
    """The registry-facing hook: (run_id, workspace_id, target_ref, result) → store SBOM."""
    use_case = build_store_image_sbom_use_case()

    def _hook(*, run_id, workspace_id, target_ref, result) -> None:
        use_case.execute(run_id=run_id, workspace_id=workspace_id, target_ref=target_ref, result=result)

    return _hook
