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

logger = logging.getLogger(__name__)


def _bucket() -> str:
    return getattr(settings, "REPORT_PDF_BUCKET", "auto-sec-reports")


def _presigned_ttl() -> int:
    return int(getattr(settings, "REPORT_PDF_S3_PRESIGNED_TTL_SECONDS", 600))


def _client(*, public: bool = False):
    """Lazy boto3 client — internal endpoint for writes, public for presigns."""
    import boto3

    endpoint = (
        getattr(settings, "REPORT_PDF_S3_PUBLIC_ENDPOINT", None)
        if public
        else getattr(settings, "REPORT_PDF_S3_ENDPOINT", None)
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=getattr(settings, "REPORT_PDF_S3_ACCESS_KEY", None),
        aws_secret_access_key=getattr(settings, "REPORT_PDF_S3_SECRET_KEY", None),
        region_name=getattr(settings, "REPORT_PDF_S3_REGION", "us-east-1"),
    )


class ReportPdfStorageService:
    @staticmethod
    def object_key(*, workspace_id: str, report_id: str) -> str:
        return f"{workspace_id}/{report_id}.pdf"

    def put_pdf(self, *, key: str, body: bytes) -> None:
        client = _client(public=False)
        self._ensure_bucket(client)
        client.put_object(Bucket=_bucket(), Key=key, Body=body, ContentType="application/pdf")
        logger.info("report.pdf_stored key=%s bytes=%s", key, len(body))

    @staticmethod
    def _ensure_bucket(client) -> None:
        """Create the reports bucket if it is missing.

        A fresh MinIO / a new AWS environment has no reports bucket yet, so
        the first generation would fail with NoSuchBucket. Creating on demand
        (idempotent — BucketAlreadyOwnedByYou is swallowed) keeps first-run
        report generation working without a separate provisioning step.
        """
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
