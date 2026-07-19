"""Process-file-upload use case — framework-free business orchestration.

Consolidates MIME validation, file type classification, and ORM
persistence into a single use case. Indexing (embed + insights) is
OPT-IN: uploads land ``not_indexed`` and only enter the pipeline when
the command explicitly asks (the AI-grounding uploader). The ask runs
through ``RequestDocumentIndexUseCase`` so the quota + circuit-breaker
policy applies uniformly.
"""

from __future__ import annotations

import datetime

from components.shared_platform.application.commands.request_document_index_command import (
    RequestDocumentIndexCommand,
    RequestDocumentIndexFailure,
)
from components.shared_platform.application.commands.upload_file_command import (
    UploadFileCommand,
    UploadFileFailure,
    UploadFileResult,
)
from components.shared_platform.application.ports.file_repository_port import (
    FileRepositoryPort,
)
from components.shared_platform.application.use_cases.request_document_index_use_case import (
    RequestDocumentIndexUseCase,
)
from components.shared_platform.domain.value_objects.file_classification import (
    classify_file,
)


class ProcessFileUploadUseCase:
    """Orchestrate file upload: classify → persist → (opt-in) index."""

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
        command: UploadFileCommand,
        *,
        file_obj,
        request=None,
    ) -> UploadFileResult | UploadFileFailure:
        # 1. Classify file
        classification = classify_file(command.content_type)

        if not classification.is_allowed:
            return UploadFileFailure(
                message=(
                    f"Invalid media type: {command.content_type}. "
                    "Only images, PDFs, and documents (doc/docx/csv/xls/xlsx) are supported."
                ),
                status_code=415,
            )

        # 2. Persist file
        entity = self._file_repo.create(
            owner_id=command.owner_id,
            workspace_id=command.workspace_id,
            file_obj=file_obj,
            file_type=classification.file_type,
        )

        # 3. Get file URL
        file_url = self._file_repo.get_absolute_file_url(
            entity.id, request=request
        ) or ""

        # 4. Opt-in indexing — never automatic. A refused index request
        # (quota, breaker, unconfigured) does not fail the upload; the
        # refusal message rides back so the caller can surface it.
        task_id = None
        index_message = ""
        processing_status = entity.processing_status
        if classification.requires_processing and command.request_indexing:
            outcome = self._index_use_case.execute(
                RequestDocumentIndexCommand(
                    file_id=entity.id,
                    requested_by_id=command.owner_id,
                    workspace_id=command.workspace_id,
                    now=command.now or datetime.datetime.now(datetime.timezone.utc),
                )
            )
            if isinstance(outcome, RequestDocumentIndexFailure):
                index_message = outcome.message
            else:
                task_id = outcome.task_id
                processing_status = outcome.processing_status

        return UploadFileResult(
            file_id=entity.id,
            file_type=classification.file_type,
            processing_status=processing_status,
            file_url=file_url,
            file_path=entity.file_path,
            created=entity.created.isoformat() if entity.created else "",
            workspace_id=entity.workspace_id or "",
            owner_id=str(entity.owner_id),
            task_id=task_id,
            index_message=index_message,
        )
