"""Unit tests for ConfirmPresignedUploadUseCase — pure, fake ports, no DB.

Indexing is opt-in: a plain confirm never dispatches; confirm with
``request_indexing`` delegates to the index policy.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from components.shared_platform.application.commands.confirm_presigned_upload_command import (
    ConfirmPresignedUploadCommand,
    ConfirmPresignedUploadFailure,
    ConfirmPresignedUploadResult,
)
from components.shared_platform.application.commands.request_document_index_command import (
    RequestDocumentIndexFailure,
    RequestDocumentIndexResult,
)
from components.shared_platform.application.use_cases.confirm_presigned_upload_use_case import (
    ConfirmPresignedUploadUseCase,
)
from components.shared_platform.domain.entities.file_entity import FileEntity


def _entity(**overrides):
    defaults = dict(
        id=7,
        owner_id=uuid4(),
        workspace_id="ws-1",
        file_path="uploads/x/y.pdf",
        file_type="pdf",
        processing_status="not_indexed",
        processing_error=None,
        processed_at=None,
        created=datetime(2026, 7, 12, 12, 0, 0),
    )
    defaults.update(overrides)
    return FileEntity(**defaults)


class FakeFileRepo:
    def __init__(self, entity=None):
        self._entity = entity

    def find_by_id(self, file_id):
        if self._entity is not None and self._entity.id == file_id:
            return self._entity
        return None

    # Unused port surface for these tests.
    def create(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def create_for_external_upload(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def update_processing_status(self, file_id, status):  # pragma: no cover
        raise NotImplementedError

    def mark_index_requested(self, file_id, *, now):  # pragma: no cover
        raise NotImplementedError

    def count_index_requests_since(self, workspace_id, *, since):  # pragma: no cover
        raise NotImplementedError

    def recent_index_outcomes(self, workspace_id, *, limit, requested_after):  # pragma: no cover
        raise NotImplementedError

    def get_absolute_file_url(self, file_id, *, request=None):  # pragma: no cover
        raise NotImplementedError


class FakeIndexUseCase:
    """Records delegation; returns a canned outcome."""

    def __init__(self, outcome=None):
        self.commands = []
        self._outcome = outcome or RequestDocumentIndexResult(
            file_id=7, processing_status="pending", dispatched=True, task_id="task-123"
        )

    def execute(self, command):
        self.commands.append(command)
        return self._outcome


def _use_case(entity, index_use_case=None):
    index_use_case = index_use_case or FakeIndexUseCase()
    return (
        ConfirmPresignedUploadUseCase(
            file_repo=FakeFileRepo(entity),
            index_use_case=index_use_case,
        ),
        index_use_case,
    )


class TestConfirmWithoutIndexIntent:
    def test_plain_confirm_never_dispatches(self):
        owner = uuid4()
        entity = _entity(owner_id=owner)
        use_case, index = _use_case(entity)

        result = use_case.execute(ConfirmPresignedUploadCommand(file_id=7, owner_id=owner))

        assert isinstance(result, ConfirmPresignedUploadResult)
        assert result.dispatched is False
        assert result.processing_status == "not_indexed"
        assert index.commands == []

    def test_missing_file_is_404(self):
        use_case, _ = _use_case(entity=None)

        result = use_case.execute(ConfirmPresignedUploadCommand(file_id=7, owner_id=uuid4()))

        assert isinstance(result, ConfirmPresignedUploadFailure)
        assert result.status_code == 404

    def test_other_owners_file_answers_like_missing(self):
        # No existence oracle: someone else's file_id must be
        # indistinguishable from a nonexistent one.
        entity = _entity(owner_id=uuid4())
        use_case, index = _use_case(entity)

        result = use_case.execute(ConfirmPresignedUploadCommand(file_id=7, owner_id=uuid4()))

        assert isinstance(result, ConfirmPresignedUploadFailure)
        assert result.status_code == 404
        assert index.commands == []


class TestConfirmWithIndexIntent:
    def test_index_intent_delegates_to_the_policy(self):
        owner = uuid4()
        entity = _entity(owner_id=owner, file_type="pdf")
        use_case, index = _use_case(entity)

        result = use_case.execute(
            ConfirmPresignedUploadCommand(file_id=7, owner_id=owner, request_indexing=True)
        )

        assert result.dispatched is True
        assert result.task_id == "task-123"
        assert result.processing_status == "pending"
        assert len(index.commands) == 1
        assert index.commands[0].file_id == 7
        assert index.commands[0].workspace_id == "ws-1"

    def test_refused_index_rides_back_without_failing_the_confirm(self):
        owner = uuid4()
        entity = _entity(owner_id=owner)
        refusal = RequestDocumentIndexFailure(
            message="Daily indexing limit reached", status_code=429, code="quota_exceeded"
        )
        use_case, _ = _use_case(entity, FakeIndexUseCase(outcome=refusal))

        result = use_case.execute(
            ConfirmPresignedUploadCommand(file_id=7, owner_id=owner, request_indexing=True)
        )

        assert isinstance(result, ConfirmPresignedUploadResult)
        assert result.dispatched is False
        assert "limit" in result.index_message

    def test_image_with_index_intent_is_a_noop(self):
        owner = uuid4()
        entity = _entity(owner_id=owner, file_type="image")
        use_case, index = _use_case(entity)

        result = use_case.execute(
            ConfirmPresignedUploadCommand(file_id=7, owner_id=owner, request_indexing=True)
        )

        assert result.dispatched is False
        assert index.commands == []
