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

from components.membership.api.permissions import IsWorkspaceOwner


class SampleDataModeView(APIView):
    """Owner-only toggle for per-workspace sample-data mode (ADR 0011). ``POST {enabled: bool}``
    flips the ``feature.sample_data_mode`` flag (the demo-mode SSOT + lever) and seeds/clears the
    sample dataset. This is the Settings control for sample-data mode."""

    permission_classes = (permissions.IsAuthenticated, IsWorkspaceOwner)
    name = "findings-sample-data-mode"

    def post(self, request, workspace_id):
        from django.utils import timezone

        from components.sample_data.application.sample_data_service import SampleDataService

        enabled = bool((request.data or {}).get("enabled"))
        actor_id = str(getattr(request.user, "id", "") or "") or None
        service = SampleDataService()
        result = (
            service.enable(str(workspace_id), now=timezone.now(), actor_id=actor_id)
            if enabled
            else service.disable(str(workspace_id), now=timezone.now(), actor_id=actor_id)
        )
        return Response({"success": True, "enabled": enabled, "data": result})


class FindingListView(APIView):
    """GET /findings/workspaces/<ws>/?severity=&status=&source=&tag=&exclude_tag=&limit=&offset=
    — the SSOT list. ``tag`` is repeatable (each occurrence an OR-group of
    comma-separated slugs; occurrences AND together); ``exclude_tag`` is AND-NOT
    (ADR 0015 D7)."""

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
        tag_store = None
        if req.tag_slug_groups or req.exclude_tag_slugs:
            tag_store = FindingProvider.build_tag_vocabulary_port()
        page = FindingProvider.build_list_findings_use_case().execute(req.to_query(tag_store=tag_store))
        return Response({"success": True, "data": FindingResource.page(page)})


class FindingStatusView(APIView):
    """POST /findings/workspaces/<ws>/<finding_id>/status/ — operator lifecycle action.

    The write behind the HUD finding-detail action row: an operator resolves, suppresses
    (dismisses as accepted-risk/false-positive — the finding-native soft "delete"), or
    reopens a finding. Membership-gated (any workspace member may act, matching the read
    gate). Never a hard delete — findings carry a lifecycle (ADR 0004 D1); this transitions
    the SSOT row and it stays auditable + re-observable.

    Body: ``{"action": "resolve" | "suppress" | "reopen"}``.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "findings-status"

    def post(self, request, workspace_id, finding_id):
        from django.utils import timezone

        from components.findings.api.requests.change_finding_status_request import (
            ChangeFindingStatusRequest,
        )
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.findings.domain.errors import FindingNotFoundError, InvalidFindingActionError
        from components.findings.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        req = ChangeFindingStatusRequest.from_request(request, workspace_id, finding_id)
        try:
            result = FindingProvider.build_change_finding_status_use_case().execute(req.to_command(at=timezone.now()))
        except FindingNotFoundError:
            return Response({"success": False, "error": "not_found"}, status=404)
        except InvalidFindingActionError as exc:
            return Response({"success": False, "error": str(exc)}, status=400)

        return Response(
            {
                "success": True,
                "data": {
                    "id": str(result.finding_id),
                    "status": result.status,
                    "changed": result.changed,
                },
            }
        )


class FindingTagView(APIView):
    """POST /findings/workspaces/<ws>/<finding_id>/tags/ — tag/untag a finding (ADR 0015 D6).

    ONE endpoint, modeled 1:1 on ``FindingStatusView``: membership-gated (any
    workspace member acts — same gate as status), single POST body
    ``{"add": [slugs…], "remove": [slugs…]}`` subsumes apply + remove (no separate
    DELETE route). ``add`` auto-creates user tags on first use (D4); ``remove`` of
    unknown slugs is a no-op. Returns the finding's full post-change tag set so the
    HUD chip row re-renders from the response.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "findings-tags"

    def post(self, request, workspace_id, finding_id):
        from django.utils import timezone

        from components.findings.api.requests.tag_finding_request import TagFindingRequest
        from components.findings.api.resources.finding_resource import FindingResource
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.findings.domain.errors import FindingNotFoundError
        from components.findings.infrastructure.services.workspace_access import is_workspace_member
        from components.shared_kernel.domain.errors import ValidationError as DomainValidationError

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        req = TagFindingRequest.from_request(request, workspace_id, finding_id)
        try:
            result = FindingProvider.build_tag_finding_use_case().execute(req.to_command(at=timezone.now()))
        except FindingNotFoundError:
            return Response({"success": False, "error": "not_found"}, status=404)
        except DomainValidationError as exc:
            # Tagging's domain errors (reserved_tag / tag_limit_exceeded / invalid_tag)
            # are caught at the shared-kernel taxonomy level — this controller never
            # imports another context's domain (Rule 3). Each error carries its own
            # ``api_code`` so the D6 contract's error strings survive the boundary.
            code = getattr(exc, "api_code", "invalid_tag")
            return Response({"success": False, "error": code, "detail": str(exc)}, status=400)

        return Response(
            {
                "success": True,
                "data": {
                    "id": str(result.finding_id),
                    "tags": [FindingResource.tag_ref_dict(ref) for ref in result.tags],
                },
            }
        )


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
