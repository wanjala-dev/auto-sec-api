"""Generate presigned PUT URLs for direct browser uploads to S3.

Mirrors ``ReportPdfStorageService`` — same boto3 client construction
(``s3v4`` signature, virtual-host addressing in prod), same separation
between operations and signing — but pointed at the Django MEDIA bucket
(``AWS_STORAGE_BUCKET_NAME``) so a single browser PUT goes straight to
the bucket and bypasses Django gunicorn for the bytes.

Why a separate service from ``ReportPdfStorageService``:
- The report-PDF bucket and the media bucket are different (different
  IAM scope, different prefix conventions). One service per bucket is
  the established pattern.
- This service generates PUT URLs; the reports one generates GET URLs.
  Different signed methods, different TTL semantics.

Why we don't sign ``ContentType`` into the URL:
- ``boto3.generate_presigned_url('put_object', Params={'ContentType': ...})``
  signs the header into the request. If the browser sends a
  *slightly different* Content-Type (e.g. ``image/jpeg`` vs the
  browser-detected ``image/jpg``), S3 returns 403
  ``SignatureDoesNotMatch``. The industry-standard fix is to not sign
  Content-Type and instead validate via ``head_object`` after upload.

Why we don't enforce file size at S3:
- Only the ``generate_presigned_post`` form supports
  ``Content-Length-Range`` policy. The PUT form has no analogue.
  For ~5MB recipient photos we accept the upload then HEAD it; if
  the response exceeds the cap we delete and surface an error to
  the user.

Dev fallback: when ``AWS_STORAGE_BUCKET_NAME`` is unset (local
``LocalMediaStorage``) the controller returns 503 so the frontend
falls back to the multipart upload endpoint. We don't run MinIO for
the media bucket in dev today — adding that is a separate task.
"""
from __future__ import annotations

import logging
from functools import cached_property

import boto3
from botocore.client import Config
from django.conf import settings

logger = logging.getLogger(__name__)


class UploadPresignedUrlService:
    """Generates presigned PUT URLs for the Django MEDIA bucket."""

    def __init__(
        self,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        location: str | None = None,
        presigned_ttl: int | None = None,
    ) -> None:
        self._bucket = bucket or getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
        self._endpoint_url = (
            endpoint_url
            or getattr(settings, "MEDIA_S3_ENDPOINT", None)
            or None
        )
        self._region = region or getattr(
            settings, "AWS_S3_REGION_NAME", "us-east-1"
        )
        self._access_key = access_key or getattr(
            settings, "MEDIA_S3_ACCESS_KEY", None
        )
        self._secret_key = secret_key or getattr(
            settings, "MEDIA_S3_SECRET_KEY", None
        )
        self._location = (
            location or getattr(settings, "AWS_LOCATION", "media") or "media"
        ).strip("/")
        self._presigned_ttl = int(
            presigned_ttl
            or getattr(
                settings, "MEDIA_S3_PRESIGNED_PUT_TTL_SECONDS", 900
            )
        )

    @property
    def enabled(self) -> bool:
        """True when an S3 bucket is configured.

        Local dev (``LocalMediaStorage``, no ``AWS_STORAGE_BUCKET_NAME``)
        evaluates to False — the controller surfaces a 503 and the
        frontend falls back to the multipart upload path.
        """
        return bool(self._bucket)

    def _build_client(self):
        kwargs: dict = {
            "service_name": "s3",
            "region_name": self._region,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            ),
        }
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        if self._access_key and self._secret_key:
            kwargs["aws_access_key_id"] = self._access_key
            kwargs["aws_secret_access_key"] = self._secret_key
        # Else: boto3's default credential chain. In prod this resolves
        # to the EC2 instance metadata service (IMDSv2), picking up the
        # ``wanjala-demo-sandbox-host`` role credentials — same as
        # ``S3MediaStorage`` for django-storages writes.
        return boto3.client(**kwargs)

    @cached_property
    def _client(self):
        return self._build_client()

    def storage_key_with_location(self, key: str) -> str:
        """Prepend the ``AWS_LOCATION`` prefix when missing.

        Django-storages adds ``media/`` to anything saved via
        ``default_storage.save()``. To stay consistent with files
        written through the multipart path we apply the same prefix
        here, so reads via ``default_storage.url(key)`` resolve the
        same way regardless of upload path.
        """
        clean_key = key.lstrip("/")
        if self._location and not clean_key.startswith(f"{self._location}/"):
            return f"{self._location}/{clean_key}"
        return clean_key

    def generate_put_url(self, *, key: str) -> str:
        """Sign a presigned PUT URL for ``key``.

        The key is location-prefixed automatically. Caller passes the
        relative storage key (e.g. ``uploads/<uuid>/photo.jpg``).
        """
        if not self.enabled:
            raise RuntimeError(
                "UploadPresignedUrlService is not configured "
                "(AWS_STORAGE_BUCKET_NAME is unset)."
            )
        full_key = self.storage_key_with_location(key)
        url = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": full_key},
            ExpiresIn=self._presigned_ttl,
            HttpMethod="PUT",
        )
        logger.info(
            "upload_presigned.put_url bucket=%s key=%s ttl=%s",
            self._bucket,
            full_key,
            self._presigned_ttl,
        )
        return url

    @property
    def presigned_ttl_seconds(self) -> int:
        return self._presigned_ttl
