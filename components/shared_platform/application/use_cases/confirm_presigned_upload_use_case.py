"""Confirm-presigned-upload use case.

The presigned-PUT flow allocates the ``File`` row BEFORE the bytes exist
(the browser uploads straight to S3 afterwards). This use case is the
second half: the browser calls it after a successful PUT to confirm the
bytes landed.

Indexing is OPT-IN and no longer dispatched here by default — uploads
stay ``not_indexed`` until a user explicitly asks. When the command
carries ``request_indexing`` (the AI-grounding uploader's
one-round-trip path), the ask is delegated to
``RequestDocumentIndexUseCase`` so the quota + circuit-breaker policy
applies uniformly. Idempotent either way.
"""

from __future__ import annotations

import datetime
import logging

from components.shared_platform.application.commands.confirm_presigned_upload_command import (
    ConfirmPresignedUploadCommand,
    ConfirmPresignedUploadFailure,
    ConfirmPresignedUploadResult,
)
from components.shared_platform.application.commands.request_document_index_command import (
    RequestDocumentIndexCommand,
    RequestDocumentIndexFailure,
)
from components.shared_platform.application.ports.file_repository_port import (
    FileRepositoryPort,
)
from components.shared_platform.application.use_cases.request_document_index_use_case import (
    RequestDocumentIndexUseCase,
)

logger = logging.getLogger(__name__)


class ConfirmPresignedUploadUseCase:
    """Look up the File → verify ownership → optionally request indexing."""

    def __init__(
        self,
        *,
        file_repo: FileRepositoryPort,
        index_use_case: RequestDocumentIndexUseCase,
    ) -> None:
        self._file_repo = file_repo
        self._index_use_case = index_use_case

    def execute(
        self,
        command: ConfirmPresignedUploadCommand,
    ) -> ConfirmPresignedUploadResult | ConfirmPresignedUploadFailure:
        entity = self._file_repo.find_by_id(command.file_id)
        # A missing row and someone else's row answer identically so the
        # endpoint can't be used to probe which file ids exist.
        if entity is None or entity.owner_id != command.owner_id:
            return ConfirmPresignedUploadFailure(
                message="File not found.",
                status_code=404,
            )

        task_id = None
        dispatched = False
        index_message = ""
        processing_status = entity.processing_status
        if command.request_indexing and entity.file_type in ("pdf", "document"):
            outcome = self._index_use_case.execute(
                RequestDocumentIndexCommand(
                    file_id=entity.id,
                    requested_by_id=command.owner_id,
                    workspace_id=entity.workspace_id or "",
                    now=datetime.datetime.now(datetime.timezone.utc),
                )
            )
            if isinstance(outcome, RequestDocumentIndexFailure):
                index_message = outcome.message
            else:
                task_id = outcome.task_id
                dispatched = outcome.dispatched
                processing_status = outcome.processing_status

        logger.info(
            "presigned_upload.confirmed file_id=%s file_type=%s indexing=%s task_id=%s owner_id=%s",
            entity.id,
            entity.file_type,
            command.request_indexing,
            task_id,
            command.owner_id,
        )
        return ConfirmPresignedUploadResult(
            file_id=entity.id,
            file_type=entity.file_type,
            processing_status=processing_status,
            dispatched=dispatched,
            task_id=task_id,
            index_message=index_message,
        )
