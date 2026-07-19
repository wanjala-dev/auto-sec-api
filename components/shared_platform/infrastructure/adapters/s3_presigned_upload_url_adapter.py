"""S3 adapter for ``PresignedUploadUrlProviderPort``.

Wraps ``UploadPresignedUrlService`` so the application use case
talks to the port, not boto3 directly.
"""
from __future__ import annotations

from components.shared_platform.application.ports.presigned_upload_url_provider_port import (
    PresignedUploadUrlProviderPort,
)
from infrastructure.storage.upload_presigned_url_service import (
    UploadPresignedUrlService,
)


class S3PresignedUploadUrlAdapter(PresignedUploadUrlProviderPort):
    def __init__(
        self, service: UploadPresignedUrlService | None = None
    ) -> None:
        self._service = service or UploadPresignedUrlService()

    @property
    def enabled(self) -> bool:
        return self._service.enabled

    def generate_put_url(self, *, key: str) -> str:
        return self._service.generate_put_url(key=key)

    @property
    def presigned_ttl_seconds(self) -> int:
        return self._service.presigned_ttl_seconds
