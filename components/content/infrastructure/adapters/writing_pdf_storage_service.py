"""Object-store adapter for Writing artifact PDFs.

Mirrors ``components.reports.infrastructure.adapters._report_pdf_storage_
service.ReportPdfStorageService`` — same bucket convention, same key
pattern. Drafts and newsletters share the ``wanjala-writing`` bucket so
the unified-documents feed can resolve presigned URLs with one client.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


def _bucket_name() -> str:
    return getattr(settings, "WRITING_S3_BUCKET", "wanjala-writing")


def _s3_client():
    """Lazy boto3/minio client — keep django config import at call time."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=getattr(settings, "AWS_S3_ENDPOINT_URL", None),
        aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", None),
        aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", None),
        region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
    )


class WritingPdfStorageService:
    """Upload + presign for writing-artifact PDFs."""

    @staticmethod
    def object_key(*, workspace_id: str, kind: str, artifact_id: str) -> str:
        # ``kind`` namespaces drafts vs newsletters within a workspace.
        return f"{workspace_id}/{kind}/{artifact_id}.pdf"

    def put_pdf(self, *, key: str, body: bytes) -> None:
        client = _s3_client()
        client.put_object(
            Bucket=_bucket_name(),
            Key=key,
            Body=body,
            ContentType="application/pdf",
        )

    def presigned_url(self, *, key: str, expires_in: int = 600) -> Optional[str]:
        client = _s3_client()
        try:
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": _bucket_name(), "Key": key},
                ExpiresIn=expires_in,
            )
        except Exception:  # noqa: BLE001
            logger.exception("writing pdf presign failed key=%s", key)
            return None
