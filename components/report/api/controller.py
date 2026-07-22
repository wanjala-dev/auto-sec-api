"""Report context REST controllers — thin primary adapters.

Each view parses the request, calls ONE use case / provider, and serialises.
Workspace membership is enforced by ``HasWorkspaceMembership`` (reads
``?workspace=``); approve additionally requires an owner/admin role via
``HasWorkspaceRole`` (``workspace_required_roles``). Download is blocked until
the report is approved — enforced here, not just advertised in the resource.
"""

from __future__ import annotations

import logging

from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from components.report.api.requests.generate_report_request import GenerateReportRequest
from components.report.api.resources.report_resource import ReportKindResource, ReportResource
from components.report.application.providers.report_provider import ReportProvider
from components.report.domain.report_kind import UnknownReportKind
from components.shared_platform.api.permissions import (
    HasWorkspaceMembership,
    HasWorkspaceRole,
)

logger = logging.getLogger(__name__)


def _workspace_id(request) -> str | None:
    return request.query_params.get("workspace") or request.query_params.get("workspace_id")


class ReportKindListController(APIView):
    """GET /report/kinds/ — the kind picker (pentest today; seam for more)."""

    name = "report-kinds"
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response({"kinds": ReportKindResource.collection()})


class ReportListCreateController(APIView):
    """GET /report/ (list) + POST /report/generate/ is a separate view; this
    handles the collection list and generate-create."""

    name = "report-list"
    permission_classes = (IsAuthenticated, HasWorkspaceMembership)

    def get(self, request):
        workspace_id = _workspace_id(request)
        if not workspace_id:
            return Response({"detail": "workspace is required."}, status=status.HTTP_400_BAD_REQUEST)
        kind = request.query_params.get("kind") or None
        reports = ReportProvider.repository().list(workspace_id=workspace_id, kind=kind)
        return Response({"results": ReportResource.collection(reports)})


class ReportGenerateController(APIView):
    """POST /report/generate/ — create a report row (draft) and enqueue async
    generation. Returns 202 with the draft row."""

    name = "report-generate"
    permission_classes = (IsAuthenticated, HasWorkspaceMembership)

    def post(self, request):
        workspace_id = _workspace_id(request) or (request.data or {}).get("workspace")
        if not workspace_id:
            return Response({"detail": "workspace is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            req = GenerateReportRequest.from_request(workspace_id=str(workspace_id), data=request.data)
        except UnknownReportKind as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        report = ReportProvider.repository().create(
            workspace_id=req.workspace_id,
            kind=req.kind,
            title=req.title,
            scope=req.scope,
            created_by_id=str(request.user.id),
        )

        from components.report.workers.tasks import generate_report

        generate_report.delay(report_id=report["id"], workspace_id=req.workspace_id)
        logger.info(
            "report.generate_enqueued report_id=%s workspace_id=%s kind=%s user_id=%s",
            report["id"],
            req.workspace_id,
            req.kind,
            request.user.id,
        )
        return Response(ReportResource.from_dict(report), status=status.HTTP_202_ACCEPTED)


class ReportDetailController(APIView):
    """GET /report/<id>/ — status + detail."""

    name = "report-detail"
    permission_classes = (IsAuthenticated, HasWorkspaceMembership)

    def get(self, request, report_id: str):
        workspace_id = _workspace_id(request)
        if not workspace_id:
            return Response({"detail": "workspace is required."}, status=status.HTTP_400_BAD_REQUEST)
        report = ReportProvider.repository().get(report_id=report_id, workspace_id=workspace_id)
        if report is None:
            return Response({"detail": "Report not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ReportResource.from_dict(report))


class ReportApproveController(APIView):
    """POST /report/<id>/approve/ — owner/admin sign-off gate."""

    name = "report-approve"
    permission_classes = (IsAuthenticated, HasWorkspaceMembership, HasWorkspaceRole)
    workspace_required_roles = ("owner", "admin")

    def post(self, request, report_id: str):
        workspace_id = _workspace_id(request)
        if not workspace_id:
            return Response({"detail": "workspace is required."}, status=status.HTTP_400_BAD_REQUEST)
        repo = ReportProvider.repository()
        report = repo.get(report_id=report_id, workspace_id=workspace_id)
        if report is None:
            return Response({"detail": "Report not found."}, status=status.HTTP_404_NOT_FOUND)
        if report["status"] not in ("generated", "approved"):
            return Response(
                {"detail": f"A report can only be approved once generated (current: {report['status']})."},
                status=status.HTTP_409_CONFLICT,
            )
        updated = repo.mark_approved(report_id=report_id, approved_by_id=str(request.user.id))
        logger.info(
            "report.approved report_id=%s workspace_id=%s approver=%s",
            report_id,
            workspace_id,
            request.user.id,
        )
        return Response(ReportResource.from_dict(updated))


class ReportDownloadController(APIView):
    """GET /report/<id>/download/ — streams the PDF once approved.

    Blocks with 409 until the report is approved (the gate is enforced here, not
    just advertised). Redirects to a presigned URL for the stored PDF."""

    name = "report-download"
    permission_classes = (IsAuthenticated, HasWorkspaceMembership)

    def get(self, request, report_id: str):
        workspace_id = _workspace_id(request)
        if not workspace_id:
            return Response({"detail": "workspace is required."}, status=status.HTTP_400_BAD_REQUEST)
        report = ReportProvider.repository().get(report_id=report_id, workspace_id=workspace_id)
        if report is None:
            return Response({"detail": "Report not found."}, status=status.HTTP_404_NOT_FOUND)
        if report["status"] != "approved":
            return Response(
                {"detail": "This report must be approved before it can be downloaded."},
                status=status.HTTP_409_CONFLICT,
            )
        if not report.get("pdf_key"):
            return Response(
                {"detail": "The report PDF is not available yet."},
                status=status.HTTP_409_CONFLICT,
            )
        storage = ReportProvider.storage()
        filename = f"{report['title'].replace(' ', '_')}.pdf"
        url = storage.presigned_url(key=report["pdf_key"], filename=filename)
        if not url:
            return Response(
                {"detail": "Could not produce a download link — try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return redirect(url)
