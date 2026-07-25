"""Read API for the CLOUD POSTURE HUD card. Thin, membership-gated, ORM-free."""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


class PostureSummaryView(APIView):
    """GET /cloud-posture/workspaces/<ws>/summary/ — latest scan + findings by severity per account."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "cloud-posture-summary"

    def get(self, request, workspace_id):
        from components.cloud_posture.api.requests.posture_summary_request import (
            PostureSummaryRequest,
        )
        from components.cloud_posture.api.resources.posture_summary_resource import (
            PostureSummaryResource,
        )
        from components.cloud_posture.infrastructure.services.posture_summary import (
            get_posture_summary,
            is_workspace_member,
        )

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)
        req = PostureSummaryRequest.from_path(workspace_id)
        summary = get_posture_summary(workspace_id=req.workspace_id)
        return Response({"success": True, "data": PostureSummaryResource.from_summary(summary).to_dict()})


class PostureFindingsView(APIView):
    """GET /cloud-posture/workspaces/<ws>/findings/?severity=&account_id= — the drill-down list."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "cloud-posture-findings"

    def get(self, request, workspace_id):
        from components.cloud_posture.infrastructure.services.posture_summary import (
            is_workspace_member,
            list_findings,
        )

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)
        findings = list_findings(
            workspace_id=workspace_id,
            severity=request.query_params.get("severity") or None,
            account_id=request.query_params.get("account_id") or None,
        )
        return Response({"success": True, "data": findings})
