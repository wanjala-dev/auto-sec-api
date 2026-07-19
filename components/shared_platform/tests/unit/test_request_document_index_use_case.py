"""Unit tests for RequestDocumentIndexUseCase — the opt-in indexing gate.

Pure fakes, no DB. Covers the whole policy: workspace scoping, indexable
kinds, idempotency, unconfigured refusal, the failure circuit-breaker,
the daily quota, and the happy dispatch path (including retry-after-fail).
"""

from __future__ import annotations

import datetime
from uuid import uuid4

from components.shared_platform.application.commands.request_document_index_command import (
    RequestDocumentIndexCommand,
    RequestDocumentIndexFailure,
    RequestDocumentIndexResult,
)
from components.shared_platform.application.use_cases.request_document_index_use_case import (
    BREAKER_FAILURE_COUNT,
    RequestDocumentIndexUseCase,
)
from components.shared_platform.domain.entities.file_entity import FileEntity

_NOW = datetime.datetime(2026, 7, 14, 12, 0, 0, tzinfo=datetime.timezone.utc)


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
        created=_NOW,
    )
    defaults.update(overrides)
    return FileEntity(**defaults)


class FakeRepo:
    def __init__(self, entity=None, *, requests_today=0, outcomes=None):
        self._entity = entity
        self.requests_today = requests_today
        self.outcomes = outcomes or []
        self.marked = []

    def find_by_id(self, file_id):
        if self._entity is not None and self._entity.id == file_id:
            return self._entity
        return None

    def mark_index_requested(self, file_id, *, now):
        self.marked.append((file_id, now))

    def count_index_requests_since(self, workspace_id, *, since):
        return self.requests_today

    def recent_index_outcomes(self, workspace_id, *, limit, requested_after):
        return self.outcomes[:limit]


class FakePort:
    def __init__(self, *, configured=True, task_id="task-9"):
        self.configured = configured
        self.task_id = task_id
        self.pdf_dispatches = []
        self.document_dispatches = []

    def dispatch_pdf_processing(self, file_id):
        self.pdf_dispatches.append(file_id)
        return self.task_id

    def dispatch_document_processing(self, file_id):
        self.document_dispatches.append(file_id)
        return self.task_id

    def is_indexing_configured(self):
        return self.configured


def _execute(entity, *, repo=None, port=None, daily_cap=50, workspace_id="ws-1"):
    repo = repo or FakeRepo(entity)
    port = port or FakePort()
    use_case = RequestDocumentIndexUseCase(
        file_repo=repo, processing_port=port, daily_cap=daily_cap
    )
    result = use_case.execute(
        RequestDocumentIndexCommand(
            file_id=7, requested_by_id=uuid4(), workspace_id=workspace_id, now=_NOW
        )
    )
    return result, repo, port


class TestScopingAndKinds:
    def test_missing_file_is_404(self):
        result, _, _ = _execute(None)
        assert isinstance(result, RequestDocumentIndexFailure)
        assert result.status_code == 404

    def test_other_workspaces_file_answers_like_missing(self):
        result, _, port = _execute(_entity(workspace_id="ws-OTHER"))
        assert isinstance(result, RequestDocumentIndexFailure)
        assert result.status_code == 404
        assert port.pdf_dispatches == []

    def test_image_is_not_indexable(self):
        result, _, _ = _execute(_entity(file_type="image"))
        assert isinstance(result, RequestDocumentIndexFailure)
        assert result.status_code == 400
        assert result.code == "not_indexable"


class TestIdempotency:
    def test_already_indexed_is_a_successful_noop(self):
        result, repo, port = _execute(_entity(processing_status="completed"))
        assert isinstance(result, RequestDocumentIndexResult)
        assert result.dispatched is False
        assert "Already indexed" in result.detail
        assert repo.marked == []
        assert port.pdf_dispatches == []

    def test_in_flight_is_a_successful_noop(self):
        for in_flight in ("pending", "processing"):
            result, repo, _ = _execute(_entity(processing_status=in_flight))
            assert isinstance(result, RequestDocumentIndexResult)
            assert result.dispatched is False
            assert repo.marked == []


class TestRefusals:
    def test_unconfigured_environment_refuses_loudly(self):
        result, repo, _ = _execute(_entity(), port=FakePort(configured=False))
        assert isinstance(result, RequestDocumentIndexFailure)
        assert result.status_code == 503
        assert result.code == "not_configured"
        assert repo.marked == []

    def test_breaker_trips_on_consecutive_recent_failures(self):
        repo = FakeRepo(_entity(), outcomes=["failed"] * BREAKER_FAILURE_COUNT)
        result, _, port = _execute(_entity(), repo=repo)
        assert isinstance(result, RequestDocumentIndexFailure)
        assert result.code == "indexing_paused"
        assert port.pdf_dispatches == []

    def test_a_recent_success_holds_the_breaker_open(self):
        outcomes = ["failed"] * (BREAKER_FAILURE_COUNT - 1) + ["completed"]
        repo = FakeRepo(_entity(), outcomes=outcomes)
        result, _, _ = _execute(_entity(), repo=repo)
        assert isinstance(result, RequestDocumentIndexResult)

    def test_quota_exceeded_is_429(self):
        repo = FakeRepo(_entity(), requests_today=3)
        result, _, port = _execute(_entity(), repo=repo, daily_cap=3)
        assert isinstance(result, RequestDocumentIndexFailure)
        assert result.status_code == 429
        assert result.code == "quota_exceeded"
        assert port.pdf_dispatches == []


class TestDispatch:
    def test_happy_path_marks_then_dispatches_pdf(self):
        result, repo, port = _execute(_entity(file_type="pdf"))
        assert isinstance(result, RequestDocumentIndexResult)
        assert result.dispatched is True
        assert result.processing_status == "pending"
        assert result.task_id == "task-9"
        assert repo.marked == [(7, _NOW)]
        assert port.pdf_dispatches == [7]

    def test_documents_route_to_the_document_task(self):
        result, _, port = _execute(_entity(file_type="document"))
        assert result.dispatched is True
        assert port.document_dispatches == [7]
        assert port.pdf_dispatches == []

    def test_failed_may_retry(self):
        result, repo, _ = _execute(_entity(processing_status="failed"))
        assert isinstance(result, RequestDocumentIndexResult)
        assert result.dispatched is True
        assert repo.marked == [(7, _NOW)]
