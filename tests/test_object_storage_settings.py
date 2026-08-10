"""Guard tests for report/SBOM object-storage settings resolution per environment.

WHY THIS FILE EXISTS
--------------------
Report PDFs and SBOMs are served to the browser via a PRESIGNED URL, and the
settings carry two endpoints: an internal one the app writes through, and a
public one the presigned URL is signed against. That split is correct for dev
(in-cluster MinIO is not reachable from the viewer's browser) and catastrophic in
prod, where the public value used to default to ``http://localhost:9100`` — a
customer clicking "download SBOM" got a URL pointing at their OWN laptop. It was
100% green in every test and 100% broken for real users, because nothing asserted
on the resolved prod shape.

So: assert the resolved shape, per environment. A prod-shaped config that
produces a localhost public endpoint, a split, or static credentials fails here.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager

import pytest

# Minimum env for ``api.settings.prod`` to import. It hard-requires each of these
# and boot-crashes without them, deliberately — see prod.py. None of them touch the
# object-storage settings under test; they are just the cost of importing the module.
PROD_MIN_ENV = {
    "SECRET_KEY": "test-only-not-a-real-key",
    "FRONTEND_URL": "https://app.auto-sec.ai",
    "DATABASE_URL": "postgres://autosec:test@postgres:5432/autosec",
}

# Every setting that must never leak a dev/MinIO value into prod.
PROD_ENDPOINT_SETTINGS = (
    "REPORT_PDF_S3_ENDPOINT",
    "REPORT_PDF_S3_PUBLIC_ENDPOINT",
    "SBOM_S3_ENDPOINT",
    "SBOM_S3_PUBLIC_ENDPOINT",
)

PROD_CREDENTIAL_SETTINGS = (
    "REPORT_PDF_S3_ACCESS_KEY",
    "REPORT_PDF_S3_SECRET_KEY",
    "SBOM_S3_ACCESS_KEY",
    "SBOM_S3_SECRET_KEY",
)


@contextmanager
def _fresh_settings(module: str, env: dict[str, str]):
    """Import a settings module under an exact env, isolated from the ambient one.

    Settings modules read ``os.environ`` at import time, so this clears the whole
    environment (not just the keys under test) — otherwise a stray
    ``REPORT_PDF_S3_ENDPOINT`` exported by the dev shell or the k8s pod would make
    the prod assertions pass or fail for the wrong reason.
    """
    saved_environ = dict(os.environ)
    saved_modules = {name: sys.modules.pop(name) for name in list(sys.modules) if name.startswith("api.settings")}
    os.environ.clear()
    os.environ.update(env)
    try:
        yield importlib.import_module(module)
    finally:
        os.environ.clear()
        os.environ.update(saved_environ)
        for name in list(sys.modules):
            if name.startswith("api.settings"):
                del sys.modules[name]
        sys.modules.update(saved_modules)


@pytest.fixture(scope="module")
def prod_settings():
    with _fresh_settings("api.settings.prod", PROD_MIN_ENV) as module:
        yield module


class TestProdResolvesToRealS3:
    """Prod must reach real S3 with the instance role — no MinIO, no split, no keys."""

    @pytest.mark.parametrize("name", PROD_ENDPOINT_SETTINGS)
    def test_endpoint_is_none_meaning_real_aws_s3(self, prod_settings, name):
        # None (not "") is load-bearing: boto3 reads None as "no endpoint override,
        # use the real AWS endpoint", while "" is a malformed override.
        assert getattr(prod_settings, name) is None, (
            f"{name} must be None in prod so boto3 targets real AWS S3. "
            "A non-None value re-introduces an S3-compatible endpoint override."
        )

    @pytest.mark.parametrize("name", PROD_ENDPOINT_SETTINGS)
    def test_endpoint_never_points_at_localhost(self, prod_settings, name):
        """THE regression this file is named for.

        Kept separate from the is-None assertion on purpose: if someone ever has a
        legitimate reason to set a prod endpoint override (a VPC S3 interface
        endpoint, say), that change relaxes the assertion above — and this one must
        still hold. A prod URL the viewer's browser follows can never be loopback.
        """
        value = getattr(prod_settings, name) or ""
        lowered = str(value).lower()
        assert "localhost" not in lowered and "127.0.0.1" not in lowered, (
            f"{name} resolves to {value!r} in prod — a presigned URL signed against "
            "a loopback origin points at the VIEWER'S OWN machine, not at us."
        )

    @pytest.mark.parametrize("name", PROD_ENDPOINT_SETTINGS)
    def test_endpoint_never_points_at_in_cluster_minio(self, prod_settings, name):
        value = str(getattr(prod_settings, name) or "").lower()
        assert "minio" not in value, f"{name} still targets in-cluster MinIO in prod: {value!r}"

    def test_there_is_no_public_internal_split(self, prod_settings):
        """Real S3 has ONE origin. base.py's comment now says so truthfully."""
        assert prod_settings.REPORT_PDF_S3_ENDPOINT == prod_settings.REPORT_PDF_S3_PUBLIC_ENDPOINT
        assert prod_settings.SBOM_S3_ENDPOINT == prod_settings.SBOM_S3_PUBLIC_ENDPOINT

    @pytest.mark.parametrize("name", PROD_CREDENTIAL_SETTINGS)
    def test_credentials_are_none_so_boto3_uses_the_instance_role(self, prod_settings, name):
        # base.py defaults these to the dev MinIO pair ("wanjala"/"wanjaladev").
        # Inheriting those in prod sends MinIO's keys to AWS and 403s every upload.
        assert getattr(prod_settings, name) is None, (
            f"{name} must be None in prod so boto3's default chain reaches IMDSv2 "
            "and picks up the k3s host instance role. Prod has NO static S3 keys."
        )

    def test_objects_land_under_their_own_prefix_of_the_shared_bucket(self, prod_settings):
        # One bucket, prefix-scoped IAM + lifecycle (terraform s3.tf / main.tf).
        assert prod_settings.REPORT_PDF_BUCKET == "autosec-prod-data"
        assert prod_settings.SBOM_S3_BUCKET == "autosec-prod-data"
        assert prod_settings.REPORT_PDF_S3_PREFIX == "reports"
        assert prod_settings.SBOM_S3_PREFIX == "sboms"
        # Distinct prefixes are what keep the IAM statements independently scopeable.
        assert prod_settings.REPORT_PDF_S3_PREFIX != prod_settings.SBOM_S3_PREFIX


class TestDevKeepsItsMinioSplit:
    """The split exists for a real reason in dev — this change must not remove it."""

    def test_base_defaults_target_minio_with_a_host_reachable_public_endpoint(self):
        with _fresh_settings("api.settings.base", {}) as base:
            assert base.REPORT_PDF_S3_ENDPOINT == "http://minio:9000"
            # Host-reachable, because the browser — not the pod — follows this one.
            assert "localhost" in base.REPORT_PDF_S3_PUBLIC_ENDPOINT
            assert base.REPORT_PDF_S3_ENDPOINT != base.REPORT_PDF_S3_PUBLIC_ENDPOINT
            # Dev keeps its own buckets, so no prefix.
            assert base.REPORT_PDF_S3_PREFIX == ""
            assert base.SBOM_S3_PREFIX == ""
            # Dev keeps static MinIO creds (there is no instance role locally).
            assert base.REPORT_PDF_S3_ACCESS_KEY
            assert base.SBOM_S3_ACCESS_KEY

    def test_sbom_inherits_the_report_minio_write_endpoint_in_dev(self):
        with _fresh_settings("api.settings.base", {}) as base:
            assert base.SBOM_S3_ENDPOINT == base.REPORT_PDF_S3_ENDPOINT

    def test_sbom_public_endpoint_needs_local_py_to_become_host_reachable(self):
        """Documents a real base.py quirk rather than asserting a prettier fiction.

        SBOM_S3_PUBLIC_ENDPOINT's fallback chain ends at SBOM_S3_ENDPOINT — the
        INTERNAL one — not at REPORT_PDF_S3_PUBLIC_ENDPOINT. So on base.py alone a
        dev SBOM presign would point at ``minio:9000``, which a browser cannot
        reach. ``local.py`` is what repairs it, by assigning the report public
        endpoint across. Left as-is (prod no longer has a public endpoint at all,
        so this is dev-only); asserted so the quirk is visible instead of lurking.
        """
        with _fresh_settings("api.settings.base", {}) as base:
            assert base.SBOM_S3_PUBLIC_ENDPOINT == base.SBOM_S3_ENDPOINT
            assert base.SBOM_S3_PUBLIC_ENDPOINT != base.REPORT_PDF_S3_PUBLIC_ENDPOINT


class TestBucketAutoCreateIsDevOnly:
    """Against real S3 the bucket is terraform-managed and MUST NOT be touched.

    The host role's ``s3:ListBucket`` is conditioned on ``s3:prefix``; a HeadBucket
    request carries no prefix context key, so the condition cannot match and the
    call 403s. The old unconditional auto-create would then try CreateBucket, get
    AccessDenied, and raise — failing every prod upload. Asserting on the boto3
    client, because "did we call HeadBucket" is the whole behaviour.
    """

    class _RecordingClient:
        def __init__(self):
            self.calls = []

        def head_bucket(self, **kwargs):
            self.calls.append(("head_bucket", kwargs))

        def create_bucket(self, **kwargs):
            self.calls.append(("create_bucket", kwargs))

    def test_report_store_skips_bucket_calls_against_real_s3(self, settings):
        from components.report.infrastructure.services.report_pdf_storage_service import (
            ReportPdfStorageService,
        )

        settings.REPORT_PDF_S3_ENDPOINT = None  # real S3
        client = self._RecordingClient()
        ReportPdfStorageService._ensure_bucket(client)
        assert client.calls == [], f"prod must not probe or create the bucket, but called: {client.calls}"

    def test_report_store_still_auto_creates_against_minio(self, settings):
        from components.report.infrastructure.services.report_pdf_storage_service import (
            ReportPdfStorageService,
        )

        settings.REPORT_PDF_S3_ENDPOINT = "http://minio:9000"
        client = self._RecordingClient()
        ReportPdfStorageService._ensure_bucket(client)
        assert [name for name, _ in client.calls] == ["head_bucket"]

    def test_sbom_store_skips_bucket_calls_against_real_s3(self, settings):
        from components.container_security.infrastructure.adapters.minio_sbom_store import (
            MinioSbomStore,
        )

        settings.SBOM_S3_ENDPOINT = None
        client = self._RecordingClient()
        MinioSbomStore._ensure_bucket(client)
        assert client.calls == []

    def test_sbom_store_still_auto_creates_against_minio(self, settings):
        from components.container_security.infrastructure.adapters.minio_sbom_store import (
            MinioSbomStore,
        )

        settings.SBOM_S3_ENDPOINT = "http://minio:9000"
        client = self._RecordingClient()
        MinioSbomStore._ensure_bucket(client)
        assert [name for name, _ in client.calls] == ["head_bucket"]

    def test_scan_artifact_store_skips_bucket_calls_against_real_s3(self, settings):
        """Prod sets SCAN_ARTIFACT_S3_ENDPOINT to the EMPTY string — present but
        falsy — so this asserts the resolved-endpoint predicate, not var presence."""
        from components.scanning.infrastructure.adapters.minio_scan_artifact_store import (
            MinioScanArtifactStore,
        )

        settings.SCAN_ARTIFACT_S3_ENDPOINT = ""
        client = self._RecordingClient()
        MinioScanArtifactStore._ensure_bucket(client, "autosec-prod-data")
        assert client.calls == []


class TestPrefixIsAppliedToObjectKeys:
    """A prefix setting nothing reads would be a silent no-op — assert the keys."""

    def test_report_key_carries_the_prefix_when_set(self, settings):
        from components.report.infrastructure.services.report_pdf_storage_service import (
            ReportPdfStorageService,
        )

        settings.REPORT_PDF_S3_PREFIX = "reports"
        key = ReportPdfStorageService.object_key(workspace_id="ws-1", report_id="r-1")
        assert key == "reports/ws-1/r-1.pdf"

    def test_report_key_is_unprefixed_when_empty(self, settings):
        from components.report.infrastructure.services.report_pdf_storage_service import (
            ReportPdfStorageService,
        )

        settings.REPORT_PDF_S3_PREFIX = ""
        key = ReportPdfStorageService.object_key(workspace_id="ws-1", report_id="r-1")
        assert key == "ws-1/r-1.pdf"

    def test_sbom_key_carries_the_prefix_when_set(self, settings):
        from uuid import uuid4

        from components.container_security.infrastructure.adapters.minio_sbom_store import (
            MinioSbomStore,
        )

        workspace_id, scan_run_id = uuid4(), uuid4()
        settings.SBOM_S3_PREFIX = "sboms"
        prefixed = MinioSbomStore.object_key(
            workspace_id=workspace_id, image_ref="alpine:3.20", scan_run_id=scan_run_id
        )
        settings.SBOM_S3_PREFIX = ""
        bare = MinioSbomStore.object_key(workspace_id=workspace_id, image_ref="alpine:3.20", scan_run_id=scan_run_id)

        assert prefixed == f"sboms/{bare}"
        assert bare.startswith(str(workspace_id))
