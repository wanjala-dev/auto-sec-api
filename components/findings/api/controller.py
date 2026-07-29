"""Read API for the Finding SSOT. Thin, membership-gated, ORM-free.

Makes the unified findings spine (ADR 0004) visible: a paginated, filterable list
of a workspace's findings — the read surface the HUD/consumers need now that
scanners (cloud_posture, logwatch) populate the SSOT. Read-only; writes stay on the
``FindingObserved`` event path (owner-persists, C2).
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


class SampleDataView(APIView):
    """POST seeds / DELETE clears the never-empty-HUD sample findings for a workspace
    (onboarding slice B). Sample rows are source-prefixed ``sample.`` and seeding is
    guarded to workspaces with no real findings — the demo/real data is never touched."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "findings-sample-data"

    def _guard(self, request, workspace_id):
        from components.findings.infrastructure.services.workspace_access import is_workspace_member

        return is_workspace_member(user=request.user, workspace_id=workspace_id)

    def post(self, request, workspace_id):
        from django.utils import timezone

        from components.findings.application.providers.finding_provider import FindingProvider

        if not self._guard(request, workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)
        result = FindingProvider.build_seed_sample_data_use_case().execute(workspace_id, now=timezone.now())
        return Response({"success": True, "data": result})

    def delete(self, request, workspace_id):
        from django.utils import timezone

        from components.findings.application.providers.finding_provider import FindingProvider

        if not self._guard(request, workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)
        result = FindingProvider.build_clear_sample_data_use_case().execute(workspace_id, now=timezone.now())
        return Response({"success": True, "data": result})


class FindingListView(APIView):
    """GET /findings/workspaces/<ws>/?severity=&status=&source=&limit=&offset= — the SSOT list."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "findings-list"

    def get(self, request, workspace_id):
        from components.findings.api.requests.list_findings_request import ListFindingsRequest
        from components.findings.api.resources.finding_resource import FindingResource
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.findings.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        req = ListFindingsRequest.from_request(request, workspace_id)
        page = FindingProvider.build_list_findings_use_case().execute(req.to_query())
        return Response({"success": True, "data": FindingResource.page(page)})


class AttckCoverageView(APIView):
    """GET /findings/workspaces/<ws>/attack-coverage/ — the materialized ATT&CK heatmap.

    Lazy materialization: returns the materialized blob (thin single-row read) and, when
    it's missing or stale, enqueues an async recompute so the heavy aggregation never runs
    in the request path. The response flags ``refreshing`` so the HUD can poll again.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "findings-attck-coverage"

    def get(self, request, workspace_id):
        from django.utils import timezone

        from components.findings.api.resources.attck_coverage_resource import AttckCoverageResource
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.findings.infrastructure.services.workspace_access import is_workspace_member
        from components.findings.infrastructure.tasks.attck_coverage_tasks import (
            recompute_workspace_attck_coverage,
        )

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        # timezone.now() respects USE_TZ (=False here → naive), matching the ORM's naive
        # computed_at so the staleness comparison never mixes naive/aware datetimes.
        snapshot, is_stale = FindingProvider.build_get_attck_coverage_use_case().execute(workspace_id, timezone.now())
        if is_stale:
            recompute_workspace_attck_coverage.delay(str(workspace_id))
        return Response({"success": True, "data": AttckCoverageResource.from_snapshot(snapshot, refreshing=is_stale)})


class ComplianceSummaryView(APIView):
    """GET /findings/workspaces/<ws>/compliance-summary/ — distinct failing controls per
    curated framework (CIS, PCI-DSS, SOC 2, ISO 27001, HIPAA, NIST, FedRAMP…), rolled up
    from open findings' compliance tags. Real failures only — no fabricated pass %.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "findings-compliance-summary"

    def get(self, request, workspace_id):
        from components.findings.api.resources.compliance_summary_resource import ComplianceSummaryResource
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.findings.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        summary = FindingProvider.build_get_compliance_summary_use_case().execute(workspace_id)
        return Response({"success": True, "data": ComplianceSummaryResource.of(summary)})
