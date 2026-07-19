"""Unit tests for ProcessFileUploadUseCase — framework-free orchestration.

Indexing is opt-in: a plain upload persists the file and stops
(``not_indexed``); only ``request_indexing`` uploads delegate to the
index policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from components.shared_platform.application.commands.request_document_index_command import (
    RequestDocumentIndexFailure,
    RequestDocumentIndexResult,
)
from components.shared_platform.application.commands.upload_file_command import (
    UploadFileCommand,
    UploadFileFailure,
    UploadFileResult,
)
from components.shared_platform.application.use_cases.process_file_upload_use_case import (
    ProcessFileUploadUseCase,
)
from components.shared_platform.domain.entities.file_entity import FileEntity

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


class FileRepositoryPortStub:
    def __init__(self):
        self.created_entities: list[FileEntity] = []
        self._next_url = "/media/file.pdf"

    def create(self, *, owner_id, workspace_id, file_obj, file_type):
        next_id = len(self.created_entities) + 1
        entity = FileEntity(
            id=next_id,
            owner_id=owner_id,
            workspace_id=workspace_id,
            file_path=f"/uploads/{file_type}_file_{next_id}",
            file_type=file_type,
            # Mirrors the model default: everything lands not_indexed.
            processing_status="not_indexed" if file_type in ("pdf", "document") else "completed",
            processing_error=None,
            processed_at=None,
            created=datetime.now(),
        )
        self.created_entities.append(entity)
        return entity

    def get_absolute_file_url(self, file_id, request=None):
        return self._next_url


class FakeIndexUseCase:
    def __init__(self, outcome=None):
        self.commands = []
        self._outcome = outcome or RequestDocumentIndexResult(
            file_id=1, processing_status="pending", dispatched=True, task_id="task-uuid-123"
        )

    def execute(self, command):
        self.commands.append(command)
        return self._outcome


def _command(content_type, *, request_indexing=False, workspace_id="ws-123"):
    return UploadFileCommand(
        owner_id=uuid4(),
        workspace_id=workspace_id,
        content_type=content_type,
        request_indexing=request_indexing,
        now=_NOW,
    )


class TestPlainUploadsDoNotIndex:
    def setup_method(self):
        self.file_repo = FileRepositoryPortStub()
        self.index = FakeIndexUseCase()
        self.use_case = ProcessFileUploadUseCase(
            file_repo=self.file_repo, index_use_case=self.index
        )

    def test_pdf_upload_lands_not_indexed_with_no_dispatch(self):
        result = self.use_case.execute(_command("application/pdf"), file_obj=MagicMock())

        assert isinstance(result, UploadFileResult)
        assert result.file_type == "pdf"
        assert result.processing_status == "not_indexed"
        assert result.task_id is None
        assert self.index.commands == []

    def test_document_upload_lands_not_indexed(self):
        result = self.use_case.execute(_command("text/csv"), file_obj=MagicMock())

        assert result.file_type == "document"
        assert result.processing_status == "not_indexed"
        assert self.index.commands == []

    def test_image_upload_unchanged(self):
        result = self.use_case.execute(_command("image/png"), file_obj=MagicMock())

        assert result.file_type == "image"
        assert result.processing_status == "completed"
        assert result.task_id is None
        assert self.index.commands == []


class TestUploadWithIndexIntent:
    def setup_method(self):
        self.file_repo = FileRepositoryPortStub()

    def test_index_intent_delegates_to_the_policy(self):
        index = FakeIndexUseCase()
        use_case = ProcessFileUploadUseCase(file_repo=self.file_repo, index_use_case=index)

        result = use_case.execute(
            _command("application/pdf", request_indexing=True), file_obj=MagicMock()
        )

        assert result.processing_status == "pending"
        assert result.task_id == "task-uuid-123"
        assert len(index.commands) == 1
        assert index.commands[0].workspace_id == "ws-123"
        assert index.commands[0].now == _NOW

    def test_refused_index_does_not_fail_the_upload(self):
        refusal = RequestDocumentIndexFailure(
            message="Daily indexing limit reached", status_code=429, code="quota_exceeded"
        )
        use_case = ProcessFileUploadUseCase(
            file_repo=self.file_repo, index_use_case=FakeIndexUseCase(outcome=refusal)
        )

        result = use_case.execute(
            _command("application/pdf", request_indexing=True), file_obj=MagicMock()
        )

        assert isinstance(result, UploadFileResult)
        assert result.processing_status == "not_indexed"
        assert "limit" in result.index_message

    def test_image_with_index_intent_never_delegates(self):
        index = FakeIndexUseCase()
        use_case = ProcessFileUploadUseCase(file_repo=self.file_repo, index_use_case=index)

        use_case.execute(_command("image/jpeg", request_indexing=True), file_obj=MagicMock())

        assert index.commands == []


class TestValidationUnchanged:
    def setup_method(self):
        self.use_case = ProcessFileUploadUseCase(
            file_repo=FileRepositoryPortStub(), index_use_case=FakeIndexUseCase()
        )

    def test_invalid_content_type_rejected(self):
        result = self.use_case.execute(
            _command("application/x-msdownload"), file_obj=MagicMock()
        )
        assert isinstance(result, UploadFileFailure)
        assert result.status_code == 415
        assert "Invalid media type" in result.message

    def test_video_and_text_plain_rejected(self):
        for content_type in ("video/mp4", "text/plain", ""):
            result = self.use_case.execute(_command(content_type), file_obj=MagicMock())
            assert isinstance(result, UploadFileFailure)
            assert result.status_code == 415

    def test_upload_without_workspace_id(self):
        result = self.use_case.execute(
            _command("image/jpeg", workspace_id=None), file_obj=MagicMock()
        )
        assert isinstance(result, UploadFileResult)
        assert result.workspace_id == ""

    def test_result_includes_file_url_and_owner_string(self):
        result = self.use_case.execute(_command("image/png"), file_obj=MagicMock())
        assert result.file_url == "/media/file.pdf"
        assert isinstance(result.owner_id, str)
