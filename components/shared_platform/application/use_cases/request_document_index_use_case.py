"""Explicit opt-in document indexing.

Indexing (chunk → embed → AI insights) is the ONLY path a document takes
into the workspace RAG store, and it never happens silently: uploads land
``not_indexed`` and stay there until a user asks. This use case is the
single gate for that ask — the index button, the retry-after-failure
button, and the grounding uploader's index-on-upload intent all come
through here, so the cost controls live in exactly one place:

- refuses when no embeddings provider is configured (503, loud — never
  queue a task that would no-op);
- a per-workspace DAILY QUOTA on index requests (bulk-upload storms can't
  silently burn tokens or saturate the worker queue);
- a failure CIRCUIT-BREAKER: when the workspace's recent index attempts
  all failed in a short window (provider outage, bad key), new requests
  pause with a clear message instead of feeding the failure.

Idempotent: re-requesting a document that is queued, processing, or
already indexed is a successful no-op. ``failed`` and ``not_indexed``
may (re-)enter the pipeline.
"""

from __future__ import annotations

import datetime
import logging

from components.shared_platform.application.commands.request_document_index_command import (
    RequestDocumentIndexCommand,
    RequestDocumentIndexFailure,
    RequestDocumentIndexResult,
)
from components.shared_platform.application.ports.file_processing_port import (
    FileProcessingPort,
)
from components.shared_platform.application.ports.file_repository_port import (
    FileRepositoryPort,
)

logger = logging.getLogger(__name__)

# Only these types have an indexing pipeline.
_INDEXABLE_TYPES = ("pdf", "document")
# Statuses allowed to (re-)enter the pipeline.
_REQUESTABLE_STATUSES = ("not_indexed", "failed")

DEFAULT_DAILY_INDEX_CAP = 50
# Breaker: this many consecutive terminal failures inside the window
# pauses new index requests for the workspace.
BREAKER_FAILURE_COUNT = 5
BREAKER_WINDOW = datetime.timedelta(hours=1)
_QUOTA_WINDOW = datetime.timedelta(hours=24)


class RequestDocumentIndexUseCase:
    def __init__(
        self,
        *,
        file_repo: FileRepositoryPort,
        processing_port: FileProcessingPort,
        daily_cap: int = DEFAULT_DAILY_INDEX_CAP,
    ) -> None:
        self._file_repo = file_repo
        self._processing_port = processing_port
        self._daily_cap = daily_cap

    def execute(
        self, command: RequestDocumentIndexCommand
    ) -> RequestDocumentIndexResult | RequestDocumentIndexFailure:
        entity = self._file_repo.find_by_id(command.file_id)
        # A missing row and another workspace's row answer identically so
        # the endpoint can't probe which file ids exist.
        if entity is None or str(entity.workspace_id or "") != str(command.workspace_id):
            return RequestDocumentIndexFailure(
                message="Document not found.", status_code=404, code="not_found"
            )

        if entity.file_type not in _INDEXABLE_TYPES:
            return RequestDocumentIndexFailure(
                message="Only PDFs and documents (doc/docx/csv/xls/xlsx) can be indexed.",
                status_code=400,
                code="not_indexable",
            )

        if entity.processing_status not in _REQUESTABLE_STATUSES:
            # Queued, processing, or already indexed — idempotent no-op.
            return RequestDocumentIndexResult(
                file_id=entity.id,
                processing_status=entity.processing_status,
                dispatched=False,
                task_id=None,
                detail=(
                    "Already indexed."
                    if entity.processing_status == "completed"
                    else "Indexing is already in progress."
                ),
            )

        if not self._processing_port.is_indexing_configured():
            return RequestDocumentIndexFailure(
                message="AI indexing is not configured for this environment yet.",
                status_code=503,
                code="not_configured",
            )

        outcomes = self._file_repo.recent_index_outcomes(
            command.workspace_id,
            limit=BREAKER_FAILURE_COUNT,
            requested_after=command.now - BREAKER_WINDOW,
        )
        if len(outcomes) >= BREAKER_FAILURE_COUNT and all(s == "failed" for s in outcomes):
            logger.warning(
                "document_index_paused workspace_id=%s consecutive_failures=%s",
                command.workspace_id,
                len(outcomes),
            )
            return RequestDocumentIndexFailure(
                message=(
                    "Indexing is paused for this workspace after repeated failures. "
                    "Try again in about an hour — if it keeps failing, contact support."
                ),
                status_code=503,
                code="indexing_paused",
            )

        used = self._file_repo.count_index_requests_since(
            command.workspace_id, since=command.now - _QUOTA_WINDOW
        )
        if used >= self._daily_cap:
            return RequestDocumentIndexFailure(
                message=(
                    f"Daily indexing limit reached ({self._daily_cap} documents in 24 hours). "
                    "Try again tomorrow, or index just the documents you need for AI."
                ),
                status_code=429,
                code="quota_exceeded",
            )

        self._file_repo.mark_index_requested(entity.id, now=command.now)
        if entity.file_type == "pdf":
            task_id = self._processing_port.dispatch_pdf_processing(entity.id)
        else:
            task_id = self._processing_port.dispatch_document_processing(entity.id)

        logger.info(
            "document_index_requested file_id=%s workspace_id=%s user_id=%s task_id=%s",
            entity.id,
            command.workspace_id,
            command.requested_by_id,
            task_id,
        )
        return RequestDocumentIndexResult(
            file_id=entity.id,
            processing_status="pending",
            dispatched=task_id is not None,
            task_id=task_id,
            detail="Indexing started.",
        )
