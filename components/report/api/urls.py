"""URL routing for the report context.

Mounted at ``report/`` in the root URL configuration (and therefore also under
``/api/v0/`` and ``/api/v1/`` via the versioned includes).
"""

from django.urls import path

from components.report.api.controller import (
    ReportApproveController,
    ReportDetailController,
    ReportDownloadController,
    ReportGenerateController,
    ReportKindListController,
    ReportListCreateController,
)

urlpatterns = [
    path("kinds/", ReportKindListController.as_view(), name=ReportKindListController.name),
    path("generate/", ReportGenerateController.as_view(), name=ReportGenerateController.name),
    path("<uuid:report_id>/approve/", ReportApproveController.as_view(), name=ReportApproveController.name),
    path("<uuid:report_id>/download/", ReportDownloadController.as_view(), name=ReportDownloadController.name),
    path("<uuid:report_id>/", ReportDetailController.as_view(), name=ReportDetailController.name),
    path("", ReportListCreateController.as_view(), name=ReportListCreateController.name),
]
