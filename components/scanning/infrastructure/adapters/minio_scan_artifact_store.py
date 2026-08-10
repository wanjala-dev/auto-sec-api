"""MinIO/S3 ScanArtifactStorePort adapter — raw scan output in object storage (ADR 0022).

Follows the ``minio_sbom_store`` conventions (lazy boto3 client, idempotent bucket
auto-create, ``*_S3_*`` settings falling back to the shared MinIO env) so the cluster
needs no new object-store deployment: MinIO in-cluster locally, real S3 in prod.

Object key: ``scan-artifacts/<workspace_id>/<source>/<scan_run_id>.json`` — a
per-workspace prefix under a single ``scan-artifacts/`` root, which is what the prod
S3 lifecycle rule and the write-scoped IAM statement both key off.

TWO deliberate departures from the SBOM adapter, both of them the point of this ADR:

1. **No presigned GET anywhere.** The SBOM adapter presigns with ``public=True`` for
   browser download, which is the path with the known prod endpoint bug. Reads here are
   server-side with our own credentials over the internal endpoint, so that bug cannot
   be inherited. If an operator-facing download is ever wanted it must go through an
   authenticated API read, not a public presign.
2. **Presigned PUT is the write path**, so object-storage credentials never enter the
   untrusted scan tier (see ``ScanArtifactStorePort``).
"""

from __future__ import annotations

import logging

from django.conf import settings

from components.scanning.application.ports.scan_artifact_store_port import (
    ArtifactUploadTarget,
    ScanArtifactStorePort,
)
from components.scanning.domain.errors import ScanArtifactStoreError

logger = logging.getLogger(__name__)

# The single root prefix every raw scan artifact lives under. Prod's S3 lifecycle rule
# and the instance-role IAM statement are both scoped to exactly this — keep them in step
# (auto-sec-infra terraform/workloads/api/{s3,main}.tf).
ARTIFACT_PREFIX = "scan-artifacts"


def _setting(name: str, fallback_name: str, default):
    """SCAN_ARTIFACT_S3_* with a fallback to the shared MinIO/report settings.

    Same fallback ladder the SBOM store uses, so a deployment that already has object
    storage configured gets the artifact channel with zero new cluster config.
    """
    value = getattr(settings, name, None)
    if value is None:
        value = getattr(settings, fallback_name, None)
    return default if value is None else value


def _bucket() -> str:
    return _setting("SCAN_ARTIFACT_S3_BUCKET", "SBOM_S3_BUCKET", "autosec-scan-artifacts")


def _put_ttl() -> int:
    # Short by design: the capability only has to survive one scan's upload.
    return int(_setting("SCAN_ARTIFACT_S3_PUT_TTL_SECONDS", "SBOM_S3_PRESIGNED_TTL_SECONDS", 3600))


def _max_bytes() -> int:
    """Hard cap on a stored artifact (ADR 0022 D4). Exceeding it is a FAILED run."""
    return int(getattr(settings, "SCAN_ARTIFACT_MAX_BYTES", 512 * 1024 * 1024))


def _targets_own_endpoint() -> bool:
    """True when this deployment configured the artifact store explicitly.

    This is the switch between the two real deployments, and it has to also govern
    CREDENTIALS or prod breaks in a nasty, quiet way: prod points the artifact store at
    real S3 (``autosec-prod-data/scan-artifacts/``) while MinIO still serves reports and
    SBOMs, so blindly inheriting ``SBOM_S3_ACCESS_KEY`` would send MinIO's keys to AWS —
    every upload 403s. Credentials therefore fall back only when the endpoint does.
    """
    return getattr(settings, "SCAN_ARTIFACT_S3_ENDPOINT", None) is not None


def _endpoint() -> str | None:
    # ALWAYS an internal endpoint (in-cluster MinIO, or AWS S3 itself). Both the Job's PUT
    # and our own GET happen inside the cluster, so the *public* endpoint — and the prod
    # bug that breaks it — is never involved. Explicitly empty means "real AWS S3".
    if _targets_own_endpoint():
        return settings.SCAN_ARTIFACT_S3_ENDPOINT or None
    return getattr(settings, "SBOM_S3_ENDPOINT", None) or None


def _credentials() -> tuple[str | None, str | None]:
    """(access key, secret) — or (None, None) to use boto3's default chain.

    (None, None) is the PROD path: the k3s host's instance role, whose policy is scoped to
    the ``scan-artifacts/*`` prefix. No static S3 keys exist in prod for this at all, and
    presigning with role credentials is valid well past our 1-hour PUT TTL.
    """
    if _targets_own_endpoint():
        return (
            getattr(settings, "SCAN_ARTIFACT_S3_ACCESS_KEY", None) or None,
            getattr(settings, "SCAN_ARTIFACT_S3_SECRET_KEY", None) or None,
        )
    return (
        getattr(settings, "SBOM_S3_ACCESS_KEY", None) or None,
        getattr(settings, "SBOM_S3_SECRET_KEY", None) or None,
    )


def _client():
    import boto3
    from botocore.config import Config

    access_key, secret_key = _credentials()
    return boto3.client(
        "s3",
        endpoint_url=_endpoint(),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=_setting("SCAN_ARTIFACT_S3_REGION", "SBOM_S3_REGION", "us-east-1"),
        # SigV4 EXPLICITLY. Without this botocore mints a legacy SigV2 presigned URL
        # (AWSAccessKeyId/Signature/Expires), which current MinIO rejects outright with
        # SignatureDoesNotMatch — verified live: the uploader reached MinIO and got a 403
        # on a perfectly-formed request. Every upload would fail, and (correctly, but
        # uselessly) fail every scan with it. AWS S3 also requires SigV4 in newer regions,
        # so this is not a MinIO quirk — it is the only correct setting for both targets.
        config=Config(signature_version="s3v4"),
    )


class MinioScanArtifactStore(ScanArtifactStorePort):
    @staticmethod
    def object_key(*, workspace_id: str, scan_run_id: str, source: str) -> str:
        # source is our own registry key ("cloud_posture.prowler") — safe in a key, but
        # normalized anyway so a future source name can never escape the prefix.
        safe_source = str(source or "unknown").replace("/", "_").replace("..", "_")
        return f"{ARTIFACT_PREFIX}/{workspace_id}/{safe_source}/{scan_run_id}.json"

    def presign_put(self, *, workspace_id: str, scan_run_id: str, source: str) -> ArtifactUploadTarget:
        bucket = _bucket()
        key = self.object_key(workspace_id=workspace_id, scan_run_id=scan_run_id, source=source)
        client = _client()
        self._ensure_bucket(client, bucket)
        try:
            url = client.generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=_put_ttl(),
            )
        except Exception as exc:
            logger.exception("scan_artifact_presign_failed key=%s", key)
            raise ScanArtifactStoreError(f"Could not mint an upload target for {key}: {exc}") from exc
        logger.info("scan_artifact_presigned key=%s bucket=%s ttl=%ss", key, bucket, _put_ttl())
        return ArtifactUploadTarget(url=url, bucket=bucket, key=key)

    def fetch(self, *, bucket: str, key: str) -> str:
        client = _client()
        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            # The Job reported success but its artifact is not there — unusable output,
            # not an empty scan. Fail loud (ADR 0022 D1's invariant, on the new transport).
            logger.exception("scan_artifact_missing bucket=%s key=%s", bucket, key)
            raise ScanArtifactStoreError(f"Scan artifact {bucket}/{key} is missing or unreadable: {exc}") from exc

        size = int(head.get("ContentLength") or 0)
        if size > _max_bytes():
            raise ScanArtifactStoreError(
                f"Scan artifact {bucket}/{key} is {size} bytes, over the "
                f"{_max_bytes()}-byte cap — refusing to load it into the worker."
            )
        if size == 0:
            raise ScanArtifactStoreError(
                f"Scan artifact {bucket}/{key} is empty — the engine wrote no result document."
            )

        try:
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:
            logger.exception("scan_artifact_read_failed bucket=%s key=%s", bucket, key)
            raise ScanArtifactStoreError(f"Could not read scan artifact {bucket}/{key}: {exc}") from exc

        logger.info("scan_artifact_fetched bucket=%s key=%s bytes=%s", bucket, key, len(body))
        return body.decode("utf-8", errors="replace")

    @staticmethod
    def _ensure_bucket(client, bucket: str) -> None:
        """Create the artifact bucket if missing — DEV (MinIO) ONLY.

        Same first-run rationale as the SBOM store, and the same prod carve-out:
        against real S3 the bucket is terraform-managed, and HeadBucket 403s because
        it carries no ``s3:prefix`` context key for ListBucket's prefix condition to
        match — then CreateBucket is denied and the whole presign raises. Prod would
        have failed its FIRST scan on this; found while migrating reports/SBOMs onto
        the same bucket, fixed here in lockstep so all three adapters agree.

        NOTE the predicate is ``_endpoint()``, NOT ``_targets_own_endpoint()``: prod
        sets SCAN_ARTIFACT_S3_ENDPOINT to the EMPTY string, so "an endpoint var is
        present" is true there while the resolved endpoint is None (real S3). Only
        the resolved value distinguishes MinIO from AWS.
        """
        if not _endpoint():
            return

        from botocore.exceptions import ClientError

        try:
            client.head_bucket(Bucket=bucket)
        except ClientError:
            try:
                client.create_bucket(Bucket=bucket)
                logger.info("scan_artifact_bucket_created bucket=%s", bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise
