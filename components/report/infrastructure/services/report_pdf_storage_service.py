"""Object-store adapter for deliverable-report PDFs.

Reuses the existing ``REPORT_PDF_*`` settings (bucket + MinIO/S3 endpoint +
presigned TTL) — the same application-bucket convention the fork already ships
for report PDFs, keyed by ``workspace_id/report_id.pdf``. Uploads use the
internal endpoint; presigned download URLs use the public endpoint so the
browser can follow them.
"""

from __future__ import annotations

import logging

from django.conf import settings

from infrastructure.storage.object_storage import build_object_storage_client

logger = logging.getLogger(__name__)


def _bucket() -> str:
    return getattr(settings, "REPORT_PDF_BUCKET", "auto-sec-reports")


def _prefix() -> str:
    """Key prefix inside the bucket — empty in dev, ``reports`` in prod.

    Dev MinIO gives reports a bucket of their own, so keys start at the workspace
    id. Prod shares ONE ``autosec-prod-data`` bucket across media/, scan-artifacts/
    and now reports/, and that prefix is exactly what the IAM statement and the
    lifecycle rule are scoped to — so it must be part of the key, not the bucket.
    """
    return str(getattr(settings, "REPORT_PDF_S3_PREFIX", "") or "").strip("/")


def _targets_own_endpoint() -> bool:
    """True when this deployment points the store at an endpoint we operate (MinIO).

    False means real AWS S3, where the bucket is terraform-managed — see
    ``_ensure_bucket`` for why that distinction has to gate bucket creation.
    """
    return bool(getattr(settings, "REPORT_PDF_S3_ENDPOINT", None))


def _presigned_ttl() -> int:
    return int(getattr(settings, "REPORT_PDF_S3_PRESIGNED_TTL_SECONDS", 600))


def _client(*, public: bool = False):
    """Lazy object-storage client — internal endpoint for writes, public for presigns.

    SigV4 is not configured here on purpose: ``build_object_storage_client`` pins it
    for every caller, which is what stops this exact defect recurring (#316). The
    factory also treats a falsy endpoint as "real AWS S3" and a missing credential
    pair as "use boto3's default chain" — precisely the prod shape this module now
    relies on, so prod needs no special-casing at the call site.
    """
    endpoint = (
        getattr(settings, "REPORT_PDF_S3_PUBLIC_ENDPOINT", None)
        if public
        else getattr(settings, "REPORT_PDF_S3_ENDPOINT", None)
    )
    return build_object_storage_client(
        endpoint_url=endpoint,
        access_key=getattr(settings, "REPORT_PDF_S3_ACCESS_KEY", None),
        secret_key=getattr(settings, "REPORT_PDF_S3_SECRET_KEY", None),
        region_name=getattr(settings, "REPORT_PDF_S3_REGION", "us-east-1"),
    )


class ReportPdfStorageService:
    @staticmethod
    def object_key(*, workspace_id: str, report_id: str) -> str:
        prefix = _prefix()
        return f"{prefix}/{workspace_id}/{report_id}.pdf" if prefix else f"{workspace_id}/{report_id}.pdf"

    def put_pdf(self, *, key: str, body: bytes) -> None:
        client = _client(public=False)
        self._ensure_bucket(client)
        client.put_object(Bucket=_bucket(), Key=key, Body=body, ContentType="application/pdf")
        logger.info("report.pdf_stored key=%s bytes=%s", key, len(body))

    @staticmethod
    def _ensure_bucket(client) -> None:
        """Create the reports bucket if it is missing — DEV (MinIO) ONLY.

        A fresh MinIO has no reports bucket yet, so the first generation would
        fail with NoSuchBucket. Creating on demand (idempotent —
        BucketAlreadyOwnedByYou is swallowed) keeps first-run report generation
        working without a separate provisioning step.

        Skipped entirely against real S3, and that is not an optimization — it is
        required for prod to work at all. The prod bucket is terraform-managed and
        the host role's ``s3:ListBucket`` is conditioned on ``s3:prefix``; a
        HeadBucket request carries no prefix context key, so the condition cannot
        match and the call 403s. The old unconditional code would then attempt
        CreateBucket, get AccessDenied (correctly — no security product's app role
        should hold s3:CreateBucket), and raise, failing every prod report upload.
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
                logger.info("report.bucket_created bucket=%s", bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise

    def presigned_url(self, *, key: str, filename: str | None = None) -> str | None:
        client = _client(public=True)
        params = {"Bucket": _bucket(), "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        try:
            return client.generate_presigned_url("get_object", Params=params, ExpiresIn=_presigned_ttl())
        except Exception:
            logger.exception("report.pdf_presign_failed key=%s", key)
            return None
