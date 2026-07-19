"""Celery adapter implementing FileProcessingPort."""

from __future__ import annotations

import logging

from components.shared_platform.application.ports.file_processing_port import (
    FileProcessingPort,
)

logger = logging.getLogger(__name__)


class CeleryFileProcessingAdapter(FileProcessingPort):

    def dispatch_pdf_processing(self, file_id: int) -> str | None:
        try:
            from components.shared_platform.infrastructure.tasks.upload_tasks import process_pdf_file

            task = process_pdf_file.delay(file_id)
            return task.id
        except Exception as exc:
            logger.error("Failed to dispatch PDF processing for file %s: %s", file_id, exc)
            return None

    def dispatch_document_processing(self, file_id: int) -> str | None:
        try:
            from components.shared_platform.infrastructure.tasks.upload_tasks import process_document_file

            task = process_document_file.delay(file_id)
            return task.id
        except Exception as exc:
            logger.error("Failed to dispatch document processing for file %s: %s", file_id, exc)
            return None

    def is_indexing_configured(self) -> bool:
        from components.shared_platform.infrastructure.tasks.upload_tasks import _embeddings_configured

        return _embeddings_configured()
