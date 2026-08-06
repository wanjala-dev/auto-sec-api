"""Integration: SBOM stored + ref recorded + endpoint serves presigned links (task #99 P1).

boto3 is faked at the adapter's ``_client`` seam (no MinIO in CI); the ORM ref row,
the post-ingest choreography, and the HTTP surface are real.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from components.container_security.infrastructure.adapters import minio_sbom_store
from components.container_security.infrastructure.adapters.minio_sbom_store import MinioSbomStore
from components.shared_kernel.application.ports.scanner_port import (
    ScanArtifact,
    ScanResult,
    ScanTarget,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SBOM_CONTENT = json.dumps(
    {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {"name": "musl", "version": "1.1.24", "type": "library"},
            {"name": "busybox", "version": "1.31.1", "type": "library"},
        ],
    }
)


class _FakeS3Client:
    """Just enough of boto3's S3 client for the adapter: bucket + object + presign."""

    def __init__(self, store):
        self._store = store

    def head_bucket(self, Bucket):
        if Bucket not in self._store["buckets"]:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def create_bucket(self, Bucket):
        self._store["buckets"].add(Bucket)

    def put_object(self, Bucket, Key, Body, ContentType):
        self._store["objects"][(Bucket, Key)] = (Body, ContentType)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        disposition = Params.get("ResponseContentDisposition", "")
        suffix = "&attachment=1" if "attachment" in disposition else ""
        return f"http://localhost:9110/{Params['Bucket']}/{Params['Key']}?sig=test{suffix}"


@pytest.fixture
def fake_s3(monkeypatch):
    store = {"buckets": set(), "objects": {}}
    monkeypatch.setattr(minio_sbom_store, "_client", lambda *, public=False: _FakeS3Client(store))
    return store


class TestMinioSbomStore:
    def test_store_writes_object_and_ref_row(self, fake_s3, workspace_factory):
        from infrastructure.persistence.container_security.models import ImageSbom

        ws = workspace_factory()
        run_id = uuid4()
        adapter = MinioSbomStore()

        stored = adapter.store(workspace_id=ws.id, scan_run_id=run_id, image_ref="alpine:3.12", content=_SBOM_CONTENT)

        # object landed, bucket auto-created
        assert ("autosec-sboms", stored.object_key) in fake_s3["objects"]
        body, content_type = fake_s3["objects"][("autosec-sboms", stored.object_key)]
        assert content_type == "application/vnd.cyclonedx+json"
        assert json.loads(body.decode())["specVersion"] == "1.6"
        # key layout: <ws>/<sha256(image_ref)>/<run>.cdx.json
        assert stored.object_key.startswith(f"{ws.id}/")
        assert stored.object_key.endswith(f"/{run_id}.cdx.json")
        # ref row recorded with display metadata
        row = ImageSbom.objects.get(scan_run_id=run_id)
        assert row.workspace_id == ws.id
        assert row.package_count == 2
        assert row.spec_version == "1.6"
        assert row.size_bytes == len(_SBOM_CONTENT.encode())

    def test_store_is_idempotent_per_scan_run(self, fake_s3, workspace_factory):
        from infrastructure.persistence.container_security.models import ImageSbom

        ws = workspace_factory()
        run_id = uuid4()
        adapter = MinioSbomStore()
        adapter.store(workspace_id=ws.id, scan_run_id=run_id, image_ref="alpine:3.12", content=_SBOM_CONTENT)
        adapter.store(workspace_id=ws.id, scan_run_id=run_id, image_ref="alpine:3.12", content=_SBOM_CONTENT)
        assert ImageSbom.objects.filter(scan_run_id=run_id).count() == 1


class TestPostIngestChoreography:
    def _scan_and_ingest(self, ws, scanner):
        # Mirror scan_tasks.run_scan's wiring: registry hook → on_completed adapter.
        from components.scanning.application.providers.scanner_registry import post_ingest_for
        from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
        from components.scanning.infrastructure.tasks import scan_tasks  # noqa: F401 (wiring parity)

        hook = post_ingest_for("container_security.trivy")
        assert hook is not None, "container_security must register a post-ingest hook"

        def on_completed(run, result):
            hook(run_id=run.id, workspace_id=run.workspace_id, target_ref=run.target_ref, result=result)

        return run_scan_and_ingest(
            workspace_id=ws.id,
            source="container_security.trivy",
            target=ScanTarget(identifier="alpine:3.12"),
            scanner=scanner,
            on_completed=on_completed,
        )

    def test_completed_scan_persists_its_sbom(self, fake_s3, workspace_factory):
        from infrastructure.persistence.container_security.models import ImageSbom

        ws = workspace_factory()
        artifact = ScanArtifact(
            kind="sbom.cyclonedx", media_type="application/vnd.cyclonedx+json", content=_SBOM_CONTENT
        )

        class _Scanner:
            def scan(self, target, on_progress=None):
                return ScanResult(findings=(), engine="trivy", artifacts=(artifact,))

        run = self._scan_and_ingest(ws, _Scanner())
        row = ImageSbom.objects.get(scan_run_id=run.id)
        assert row.image_ref == "alpine:3.12"
        assert row.package_count == 2

    def test_sbom_storage_failure_never_fails_the_scan(self, monkeypatch, workspace_factory):
        # THE POLICY, end to end: storage blowing up leaves the run COMPLETED.
        from infrastructure.persistence.scanning.models import ScanRun

        def _boom(*, public=False):
            raise RuntimeError("minio down")

        monkeypatch.setattr(minio_sbom_store, "_client", _boom)
        ws = workspace_factory()
        artifact = ScanArtifact(
            kind="sbom.cyclonedx", media_type="application/vnd.cyclonedx+json", content=_SBOM_CONTENT
        )

        class _Scanner:
            def scan(self, target, on_progress=None):
                return ScanResult(findings=(), engine="trivy", artifacts=(artifact,))

        run = self._scan_and_ingest(ws, _Scanner())
        assert ScanRun.objects.get(id=run.id).status == ScanRun.Status.COMPLETED

    def test_no_artifact_records_nothing(self, fake_s3, workspace_factory):
        from infrastructure.persistence.container_security.models import ImageSbom

        ws = workspace_factory()

        class _Scanner:
            def scan(self, target, on_progress=None):
                return ScanResult(findings=(), engine="trivy")

        run = self._scan_and_ingest(ws, _Scanner())
        assert not ImageSbom.objects.filter(scan_run_id=run.id).exists()


class TestSbomEndpoint:
    _URL = "/container-security/workspaces/{ws}/scans/{run}/sbom/"

    @pytest.fixture
    def flags_on(self, monkeypatch):
        from components.shared_platform.application.providers import feature_flags_provider as ff

        class _AllOn:
            def is_feature_enabled(self, *a, **k):
                return True

        monkeypatch.setattr(ff, "get_feature_flags_provider", lambda: _AllOn())
        # the controller imports the symbol from the provider module at call time
        import components.container_security.api.controller  # noqa: F401

        return True

    def _stored(self, ws, fake_s3):
        run_id = uuid4()
        MinioSbomStore().store(workspace_id=ws.id, scan_run_id=run_id, image_ref="alpine:3.12", content=_SBOM_CONTENT)
        return run_id

    def test_member_gets_metadata_and_presigned_links(
        self, fake_s3, flags_on, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        run_id = self._stored(ws, fake_s3)

        api_client.force_authenticate(owner)
        resp = api_client.get(self._URL.format(ws=ws.id, run=run_id))

        assert resp.status_code == 200, resp.content
        data = resp.json()["data"]
        assert data["scan_run_id"] == str(run_id)
        assert data["image_ref"] == "alpine:3.12"
        assert data["package_count"] == 2
        assert data["spec_version"] == "1.6"
        assert data["fetch_url"].startswith("http://localhost:9110/autosec-sboms/")
        assert "attachment=1" in data["download_url"]
        assert "attachment=1" not in data["fetch_url"]

    def test_non_member_is_forbidden(self, fake_s3, flags_on, api_client, user_factory, workspace_factory):
        ws = workspace_factory()
        run_id = self._stored(ws, fake_s3)
        outsider = user_factory()

        api_client.force_authenticate(outsider)
        resp = api_client.get(self._URL.format(ws=ws.id, run=run_id))
        assert resp.status_code == 403

    def test_anonymous_is_unauthorized(self, fake_s3, flags_on, api_client, workspace_factory):
        ws = workspace_factory()
        run_id = self._stored(ws, fake_s3)
        resp = api_client.get(self._URL.format(ws=ws.id, run=run_id))
        assert resp.status_code in (401, 403)

    def test_missing_sbom_is_an_honest_404(self, flags_on, api_client, user_factory, workspace_factory):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        api_client.force_authenticate(owner)
        resp = api_client.get(self._URL.format(ws=ws.id, run=uuid4()))
        assert resp.status_code == 404
        assert resp.json()["error"] == "sbom_not_available"
