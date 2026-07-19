"""Request-presigned-upload use case.

Generates a presigned PUT URL the browser can use to upload bytes
directly to S3, plus a paired ``File`` row so downstream FK/M2M
relationships (e.g. ``Recipient.multimedia``) work without the bytes
traversing Django gunicorn.
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import PurePosixPath

from components.shared_platform.application.commands.request_presigned_upload_command import (
    PresignedUploadFailure,
    PresignedUploadResult,
    RequestPresignedUploadCommand,
)
from components.shared_platform.application.ports.file_repository_port import (
    FileRepositoryPort,
)
from components.shared_platform.application.ports.presigned_upload_url_provider_port import (
    PresignedUploadUrlProviderPort,
)
from components.shared_platform.domain.value_objects.file_classification import (
    classify_file,
)

logger = logging.getLogger(__name__)


_FILENAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    """Strip everything but ``[A-Za-z0-9._-]`` from a filename.

    Storage keys end up as URL path segments, so any character S3 would
    have to percent-encode (spaces, parens, unicode) becomes a footgun
    on the way back out. A 64-char ceiling keeps the full key under
    the 120-char Recipient.photo_url column.
    """
    candidate = (name or "").strip() or "upload"
    p = PurePosixPath(candidate)
    stem = _FILENAME_SANITIZE_RE.sub("-", p.stem).strip("-_.") or "upload"
    suffix = _FILENAME_SANITIZE_RE.sub("", p.suffix.lower())[:8]
    return f"{stem[:64]}{suffix}"


class RequestPresignedUploadUseCase:
    """Validate → allocate File row → sign PUT URL → return."""

    def __init__(
        self,
        *,
        file_repo: FileRepositoryPort,
        presigned_url_provider: PresignedUploadUrlProviderPort,
    ) -> None:
        self._file_repo = file_repo
        self._presigned_url_provider = presigned_url_provider

    def execute(
        self,
        command: RequestPresignedUploadCommand,
    ) -> PresignedUploadResult | PresignedUploadFailure:
        if not self._presigned_url_provider.enabled:
            # Local dev (LocalMediaStorage) — frontend falls back to
            # the multipart upload endpoint.
            return PresignedUploadFailure(
                message=(
                    "Presigned uploads are not configured in this "
                    "environment. Use the multipart upload endpoint."
                ),
                status_code=503,
            )

        classification = classify_file(command.content_type)
        if not classification.is_allowed:
            return PresignedUploadFailure(
                message=(
                    f"Invalid media type: {command.content_type}. "
                    "Only images, PDFs, and documents (doc/docx/csv/xls/xlsx) are supported."
                ),
                status_code=415,
            )

        safe_name = _sanitize_filename(command.filename)
        storage_key = f"uploads/{uuid.uuid4()}/{safe_name}"

        entity = self._file_repo.create_for_external_upload(
            owner_id=command.owner_id,
            workspace_id=command.workspace_id,
            storage_key=storage_key,
            file_type=classification.file_type,
        )

        put_url = self._presigned_url_provider.generate_put_url(
            key=storage_key,
        )

        logger.info(
            "presigned_upload.issued file_id=%s key=%s owner_id=%s workspace_id=%s",
            entity.id,
            storage_key,
            command.owner_id,
            command.workspace_id,
        )
        return PresignedUploadResult(
            file_id=entity.id,
            key=storage_key,
            put_url=put_url,
            expires_in=self._presigned_url_provider.presigned_ttl_seconds,
        )
