"""Unit tests for the image-SBOM use cases (task #99 P1) — fake port, no DB, no boto3."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import pytest

from components.container_security.application.ports.sbom_store_port import (
    SbomStorePort,
    StoredSbom,
)
from components.container_security.application.use_cases.get_image_sbom_use_case import (
    GetImageSbomUseCase,
)
from components.container_security.application.use_cases.store_image_sbom_use_case import (
    StoreImageSbomUseCase,
)
from components.shared_kernel.application.ports.scanner_port import ScanArtifact, ScanResult

pytestmark = pytest.mark.unit


class _FakeSbomStore(SbomStorePort):
    def __init__(self):
        self.stored: dict = {}

    def store(self, *, workspace_id, scan_run_id, image_ref, content):
        doc = json.loads(content)
        sbom = StoredSbom(
            scan_run_id=scan_run_id,
            workspace_id=workspace_id,
            image_ref=image_ref,
            format="cyclonedx",
            spec_version=str(doc.get("specVersion") or ""),
            bucket="autosec-sboms",
            object_key=f"{workspace_id}/deadbeef/{scan_run_id}.cdx.json",
            size_bytes=len(content.encode()),
            package_count=len(doc.get("components") or []),
            created_at=datetime(2026, 8, 5, 12, 0, 0),
        )
        self.stored[scan_run_id] = sbom
        return sbom

    def find_for_scan(self, *, workspace_id, scan_run_id):
        sbom = self.stored.get(scan_run_id)
        return sbom if sbom and sbom.workspace_id == workspace_id else None

    def presigned_url(self, *, sbom, download_filename=None):
        suffix = f"?dl={download_filename}" if download_filename else ""
        return f"http://minio/{sbom.object_key}{suffix}"


def _result(artifacts=()):
    return ScanResult(findings=(), engine="trivy", artifacts=tuple(artifacts))


_SBOM_CONTENT = json.dumps(
    {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "musl", "version": "1.1.24"}]}
)


class TestStoreImageSbomUseCase:
    def test_stores_the_cyclonedx_artifact(self):
        store = _FakeSbomStore()
        run_id, ws_id = uuid4(), uuid4()
        artifact = ScanArtifact(
            kind="sbom.cyclonedx", media_type="application/vnd.cyclonedx+json", content=_SBOM_CONTENT
        )

        stored = StoreImageSbomUseCase(store).execute(
            run_id=run_id, workspace_id=ws_id, target_ref="alpine:3.12", result=_result([artifact])
        )

        assert stored is not None
        assert store.stored[run_id].image_ref == "alpine:3.12"
        assert store.stored[run_id].package_count == 1
        assert store.stored[run_id].spec_version == "1.6"

    def test_absent_artifact_is_an_honest_no_op(self):
        # THE POLICY: no SBOM on the result (the engine pass failed) → store nothing,
        # return None, never raise — the completed vuln scan stands.
        store = _FakeSbomStore()
        stored = StoreImageSbomUseCase(store).execute(
            run_id=uuid4(), workspace_id=uuid4(), target_ref="alpine:3.12", result=_result()
        )
        assert stored is None
        assert store.stored == {}

    def test_ignores_unrelated_artifact_kinds(self):
        store = _FakeSbomStore()
        other = ScanArtifact(kind="raw.report", media_type="application/json", content="{}")
        stored = StoreImageSbomUseCase(store).execute(
            run_id=uuid4(), workspace_id=uuid4(), target_ref="alpine:3.12", result=_result([other])
        )
        assert stored is None


class TestGetImageSbomUseCase:
    def test_returns_view_with_both_presigned_urls(self):
        store = _FakeSbomStore()
        run_id, ws_id = uuid4(), uuid4()
        artifact = ScanArtifact(
            kind="sbom.cyclonedx", media_type="application/vnd.cyclonedx+json", content=_SBOM_CONTENT
        )
        StoreImageSbomUseCase(store).execute(
            run_id=run_id, workspace_id=ws_id, target_ref="alpine:3.12", result=_result([artifact])
        )

        view = GetImageSbomUseCase(store).execute(workspace_id=ws_id, scan_run_id=run_id)

        assert view is not None
        assert view.image_ref == "alpine:3.12"
        assert view.package_count == 1
        assert view.fetch_url and "dl=" not in view.fetch_url
        assert view.download_url and f"dl=sbom-{run_id}.cdx.json" in view.download_url

    def test_missing_sbom_returns_none(self):
        assert GetImageSbomUseCase(_FakeSbomStore()).execute(workspace_id=uuid4(), scan_run_id=uuid4()) is None

    def test_workspace_scoping_is_enforced_by_the_lookup(self):
        # A run id from ANOTHER workspace must not resolve — tenant isolation at the port.
        store = _FakeSbomStore()
        run_id, ws_id = uuid4(), uuid4()
        artifact = ScanArtifact(
            kind="sbom.cyclonedx", media_type="application/vnd.cyclonedx+json", content=_SBOM_CONTENT
        )
        StoreImageSbomUseCase(store).execute(
            run_id=run_id, workspace_id=ws_id, target_ref="alpine:3.12", result=_result([artifact])
        )
        assert GetImageSbomUseCase(store).execute(workspace_id=uuid4(), scan_run_id=run_id) is None
