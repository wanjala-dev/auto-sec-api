"""MinIO/S3 SbomStorePort adapter — object body + ImageSbom reference row.

Follows the report-PDF storage conventions
(``components/report/infrastructure/services/report_pdf_storage_service.py``):
internal endpoint for writes / public endpoint for presigns, idempotent bucket
auto-create, presigned GET with optional attachment disposition.

The client itself is NOT mirrored — it comes from
``infrastructure.storage.object_storage.build_object_storage_client``. This module
originally noted that a shared storage util was rejected "until a third consumer
appears"; three more appeared (scan artifacts, writing PDFs, media uploads), and
each hand-rolled client re-introduced the same SigV2 presign defect. The client
construction is now shared; the settings ladder stays owned here.

Settings are ``SBOM_S3_*`` with env fallbacks to the ``REPORT_PDF_S3_*`` env vars,
so the existing MinIO deployment serves SBOMs with zero new cluster config.
Object key: ``<workspace_id>/<sha256(image_ref)>/<scan_run_id>.cdx.json``.
"""

from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from django.conf import settings

from components.container_security.application.ports.sbom_store_port import (
    SbomStorePort,
    StoredSbom,
)
from infrastructure.storage.object_storage import build_object_storage_client

logger = logging.getLogger(__name__)


def _bucket() -> str:
    return getattr(settings, "SBOM_S3_BUCKET", "autosec-sboms")


def _prefix() -> str:
    """Key prefix inside the bucket — empty in dev, ``sboms`` in prod.

    Same rationale as the report store's ``_prefix``: dev MinIO gives SBOMs their
    own bucket, prod shares ONE ``autosec-prod-data`` bucket whose IAM and
    lifecycle rules are prefix-scoped. Stored on the ImageSbom row at write time,
    so already-written objects keep resolving if the prefix ever changes.
    """
    return str(getattr(settings, "SBOM_S3_PREFIX", "") or "").strip("/")


def _targets_own_endpoint() -> bool:
    """True when this deployment points the store at an endpoint we operate (MinIO)."""
    return bool(getattr(settings, "SBOM_S3_ENDPOINT", None))


def _presigned_ttl() -> int:
    return int(getattr(settings, "SBOM_S3_PRESIGNED_TTL_SECONDS", 600))


def _client(*, public: bool = False):
    """Lazy object-storage client — internal endpoint for writes, public for presigns.

    SigV4 comes from ``build_object_storage_client``; see the report store's
    ``_client`` for why it must not be re-specified here.
    """
    endpoint = (
        getattr(settings, "SBOM_S3_PUBLIC_ENDPOINT", None) if public else getattr(settings, "SBOM_S3_ENDPOINT", None)
    )
    return build_object_storage_client(
        endpoint_url=endpoint,
        access_key=getattr(settings, "SBOM_S3_ACCESS_KEY", None),
        secret_key=getattr(settings, "SBOM_S3_SECRET_KEY", None),
        region_name=getattr(settings, "SBOM_S3_REGION", "us-east-1"),
    )


class MinioSbomStore(SbomStorePort):
    @staticmethod
    def object_key(*, workspace_id: UUID, image_ref: str, scan_run_id: UUID) -> str:
        digest = hashlib.sha256(image_ref.encode("utf-8")).hexdigest()
        key = f"{workspace_id}/{digest}/{scan_run_id}.cdx.json"
        prefix = _prefix()
        return f"{prefix}/{key}" if prefix else key

    def store(self, *, workspace_id: UUID, scan_run_id: UUID, image_ref: str, content: str) -> StoredSbom:
        from infrastructure.persistence.container_security.models import ImageSbom

        body = content.encode("utf-8")
        key = self.object_key(workspace_id=workspace_id, image_ref=image_ref, scan_run_id=scan_run_id)
        digest = hashlib.sha256(image_ref.encode("utf-8")).hexdigest()
        spec_version, package_count = _sbom_metadata(content)

        client = _client(public=False)
        self._ensure_bucket(client)
        client.put_object(Bucket=_bucket(), Key=key, Body=body, ContentType="application/vnd.cyclonedx+json")

        # Idempotent per scan run: a Celery redelivery overwrites the same object and
        # updates the same row rather than duplicating (scan_run_id is unique).
        row, _created = ImageSbom.objects.update_or_create(
            scan_run_id=scan_run_id,
            defaults={
                "workspace_id": workspace_id,
                "image_ref": image_ref[:512],
                "image_ref_digest": digest,
                "format": "cyclonedx",
                "spec_version": spec_version,
                "bucket": _bucket(),
                "object_key": key,
                "size_bytes": len(body),
                "package_count": package_count,
            },
        )
        logger.info("sbom_stored key=%s bytes=%s packages=%s", key, len(body), package_count)
        return _to_dto(row)

    def find_for_scan(self, *, workspace_id: UUID, scan_run_id: UUID) -> StoredSbom | None:
        from infrastructure.persistence.container_security.models import ImageSbom

        row = ImageSbom.objects.filter(workspace_id=workspace_id, scan_run_id=scan_run_id).first()
        return _to_dto(row) if row else None

    def presigned_url(self, *, sbom: StoredSbom, download_filename: str | None = None) -> str | None:
        client = _client(public=True)
        params = {"Bucket": sbom.bucket, "Key": sbom.object_key}
        if download_filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_filename}"'
        try:
            return client.generate_presigned_url("get_object", Params=params, ExpiresIn=_presigned_ttl())
        except Exception:
            logger.exception("sbom_presign_failed key=%s", sbom.object_key)
            return None

    @staticmethod
    def _ensure_bucket(client) -> None:
        """Create the SBOM bucket if missing — DEV (MinIO) ONLY.

        Idempotent, same first-run rationale as the report bucket: a fresh MinIO
        must not fail the first stored SBOM. Skipped against real S3, where the
        bucket is terraform-managed and a HeadBucket carries no ``s3:prefix``
        context key for the prefix-conditioned ListBucket grant to match — it 403s,
        and the CreateBucket fallback is denied too. See the report store's
        ``_ensure_bucket`` for the full write-up.
        """
        if not _targets_own_endpoint():
            return

        from botocore.exceptions import ClientError

        bucket = _bucket()
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError:
            try:
                client.create_bucket(Bucket=bucket)
                logger.info("sbom_bucket_created bucket=%s", bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise


def _sbom_metadata(content: str) -> tuple[str, int]:
    """(specVersion, component count) off the CycloneDX body — display metadata only."""
    import json

    try:
        doc = json.loads(content)
    except ValueError:
        return "", 0
    if not isinstance(doc, dict):
        return "", 0
    components = doc.get("components")
    count = len(components) if isinstance(components, list) else 0
    return str(doc.get("specVersion") or ""), count


def _to_dto(row) -> StoredSbom:
    return StoredSbom(
        scan_run_id=row.scan_run_id,
        workspace_id=row.workspace_id,
        image_ref=row.image_ref,
        format=row.format,
        spec_version=row.spec_version,
        bucket=row.bucket,
        object_key=row.object_key,
        size_bytes=row.size_bytes,
        package_count=row.package_count,
        created_at=row.created_at,
    )
