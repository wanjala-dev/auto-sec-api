"""Infrastructure adapter: expose generated report PDFs as library documents.

Reads the ``Report`` ORM and builds unified-document rows (the shape the Files
library / ``/documents/`` aggregator emits) for reports that have a downloadable
PDF. The ``file_url`` points at the report download endpoint with ``inline=1``
so the library's authed blob-fetch works unchanged.

Infrastructure layer — free to import Django + the ORM. The application-layer
provider wires this in; the unified-documents controller calls it through the
provider so shared_platform never reaches into report's ORM directly.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Reports are documents once they have a rendered, downloadable PDF.
_DOWNLOADABLE_STATUSES = ("generated", "approved")

# Library ``source`` label for a report document (distinct from upload sources
# so the frontend can tab/badge it as a report).
REPORT_SOURCE = "report"


class ReportDocumentRepository:
    """Lists the workspace's downloadable reports as unified-document rows."""

    def list_documents(self, workspace_id: str, *, request=None) -> list[dict[str, Any]]:
        from django.urls import reverse

        from infrastructure.persistence.report.models import Report

        reports = (
            Report.objects.filter(workspace_id=workspace_id, status__in=_DOWNLOADABLE_STATUSES)
            .exclude(pdf_key="")
            .select_related("approved_by", "created_by")
            .order_by("-created_at")
        )

        rows: list[dict[str, Any]] = []
        for report in reports:
            # Inline download URL — the library blob-fetches this like any
            # protected PDF; ``inline=1`` previews a generated draft too.
            path = reverse("report-download", kwargs={"report_id": report.id})
            url = f"{path}?workspace={workspace_id}&inline=1"
            file_url = request.build_absolute_uri(url) if request is not None else url

            owner = report.approved_by or report.created_by
            owner_name = ""
            if owner is not None:
                owner_name = owner.get_full_name() or getattr(owner, "username", "") or str(owner)

            rows.append(
                {
                    # Prefixed id so it never collides with an integer File pk and
                    # the frontend can route a report row to its download/preview.
                    "id": f"report-{report.id}",
                    "report_id": str(report.id),
                    "filename": f"{report.title}.pdf",
                    "file_url": file_url,
                    "file_type": "pdf",
                    "source": REPORT_SOURCE,
                    "processing_status": "ready",
                    "ai_insights": {},
                    "owner": str(owner.id) if owner is not None else None,
                    "owner_name": owner_name,
                    "workspace_id": str(workspace_id),
                    "pdf_page_count": None,
                    "created": report.created_at.isoformat() if report.created_at else "",
                    "processed_at": report.pdf_generated_at.isoformat() if report.pdf_generated_at else None,
                    "import_info": None,
                    "workflow_runs": [],
                    # Report-specific extras the library can badge on.
                    "report_kind": report.kind,
                    "report_status": report.status,
                }
            )

        logger.info("report_documents.listed workspace_id=%s count=%d", workspace_id, len(rows))
        return rows
