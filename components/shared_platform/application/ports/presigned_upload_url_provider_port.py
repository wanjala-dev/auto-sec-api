"""Port for generating presigned PUT URLs for direct browser uploads.

Abstracts the storage backend so the application use case stays
framework-free. Production adapter wraps boto3 against S3; tests use a
fake that records calls without hitting AWS.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class PresignedUploadUrlProviderPort(ABC):
    """Generates presigned PUT URLs for ``key`` so the browser can
    upload bytes directly to object storage."""

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """``False`` when the storage backend is not S3-backed.

        Local dev (``LocalMediaStorage``) returns False; the controller
        then surfaces a 503 and the frontend falls back to the
        multipart upload path.
        """

    @abstractmethod
    def generate_put_url(self, *, key: str) -> str:
        """Generate a presigned PUT URL for ``key``.

        The key is the *relative* storage path (e.g.
        ``uploads/<uuid>/photo.jpg``); the implementation handles any
        location prefixing (``AWS_LOCATION``).
        """

    @property
    @abstractmethod
    def presigned_ttl_seconds(self) -> int:
        """How long the signed URL is valid for. Used to set
        ``expires_in`` in the controller response so the client knows
        when to re-request."""
