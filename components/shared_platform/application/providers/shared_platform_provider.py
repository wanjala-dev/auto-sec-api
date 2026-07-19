"""Composition root for the Shared Platform bounded context.

This provider wires concrete infrastructure adapters to application use cases.
"""

from __future__ import annotations

import os

from components.shared_platform.application.use_cases.confirm_presigned_upload_use_case import (
    ConfirmPresignedUploadUseCase,
)
from components.shared_platform.application.use_cases.process_file_upload_use_case import (
    ProcessFileUploadUseCase,
)
from components.shared_platform.application.use_cases.request_document_index_use_case import (
    DEFAULT_DAILY_INDEX_CAP,
    RequestDocumentIndexUseCase,
)
from components.shared_platform.application.use_cases.request_presigned_upload_use_case import (
    RequestPresignedUploadUseCase,
)
from components.shared_platform.infrastructure.adapters.celery_file_processing_adapter import (
    CeleryFileProcessingAdapter,
)
from components.shared_platform.infrastructure.adapters.orm_file_repository import (
    OrmFileRepository,
)
from components.shared_platform.infrastructure.adapters.s3_presigned_upload_url_adapter import (
    S3PresignedUploadUrlAdapter,
)


def _daily_index_cap() -> int:
    try:
        return int(os.environ.get("DOCUMENT_INDEX_DAILY_CAP", DEFAULT_DAILY_INDEX_CAP))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_INDEX_CAP


class SharedPlatformProvider:
    """Composition root that builds fully-wired use case instances."""

    @staticmethod
    def build_file_repository() -> OrmFileRepository:
        return OrmFileRepository()

    @staticmethod
    def build_request_document_index_use_case() -> RequestDocumentIndexUseCase:
        return RequestDocumentIndexUseCase(
            file_repo=OrmFileRepository(),
            processing_port=CeleryFileProcessingAdapter(),
            daily_cap=_daily_index_cap(),
        )

    @staticmethod
    def build_process_file_upload_use_case() -> ProcessFileUploadUseCase:
        return ProcessFileUploadUseCase(
            file_repo=OrmFileRepository(),
            index_use_case=SharedPlatformProvider.build_request_document_index_use_case(),
        )

    @staticmethod
    def build_request_presigned_upload_use_case() -> RequestPresignedUploadUseCase:
        return RequestPresignedUploadUseCase(
            file_repo=OrmFileRepository(),
            presigned_url_provider=S3PresignedUploadUrlAdapter(),
        )

    @staticmethod
    def build_confirm_presigned_upload_use_case() -> ConfirmPresignedUploadUseCase:
        return ConfirmPresignedUploadUseCase(
            file_repo=OrmFileRepository(),
            index_use_case=SharedPlatformProvider.build_request_document_index_use_case(),
        )
