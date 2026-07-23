"""Composition root: the report-documents source for the Files library.

Wires the report-document reader (infrastructure) so the unified-documents
controller can fold generated report PDFs into ``/documents/`` without reaching
into report's ORM directly. Application layer — no Django/ORM import here; the
adapter import is deferred into the getter (the context's own infrastructure
module, not ``infrastructure.persistence``).
"""

from __future__ import annotations


def get_report_documents_reader():
    """Return the report-document reader adapter (composition root)."""
    from components.report.infrastructure.repositories.report_document_repository import (
        ReportDocumentRepository,
    )

    return ReportDocumentRepository()
