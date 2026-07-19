"""Celery task shim — delegates to canonical component module.

This file exists so that ``celery.autodiscover_tasks()`` (which scans
INSTALLED_APPS) can find and register the tasks defined in the
components layer.
"""
from components.shared_platform.infrastructure.tasks.upload_tasks import (  # noqa: F401
    process_document_file,
    process_pdf_file,
    process_pending_pdfs,
    _extract_file_insights,
)
