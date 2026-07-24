"""REST surface for the provenance/access graph (read-only, workspace-scoped).

Thin primary adapter: parse the request, call the application service through
its provider, wrap the result in a resource DTO. Gated by
``feature.provenance_graph`` and active workspace membership. No business logic,
no ORM.
"""

from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.provenance.api.requests.graph_requests import (
    HallTreeQueryRequest,
    LeastPrivilegeQueryRequest,
)
from components.provenance.api.resources.graph_resources import (
    AccessReviewResource,
    BlastRadiusResource,
    GraphOverviewResource,
    HallTreeResource,
    LeastPrivilegeResource,
)
from components.provenance.application.providers.provenance_provider import get_provenance_service
from components.shared_platform.api.permissions import HasWorkspaceMembership, RequiresFeatureFlag

_FLAG = "feature.provenance_graph"


class _BaseProvenanceView(APIView):
    permission_classes = (permissions.IsAuthenticated, HasWorkspaceMembership, RequiresFeatureFlag)
    feature_flag_key = _FLAG


class GraphOverviewView(_BaseProvenanceView):
    name = "provenance-graph-overview"

    def get(self, request, workspace_id):
        result = get_provenance_service().graph_overview(workspace_id=workspace_id)
        return Response({"success": True, "data": GraphOverviewResource.from_result(result).to_dict()})


class VendorBlastRadiusView(_BaseProvenanceView):
    name = "provenance-blast-radius"

    def get(self, request, workspace_id, actor_id):
        result = get_provenance_service().vendor_blast_radius(workspace_id=workspace_id, actor_id=actor_id)
        if result is None:
            return Response({"success": False, "error": "actor not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": BlastRadiusResource.from_result(result).to_dict()})


class AccessReviewView(_BaseProvenanceView):
    name = "provenance-access-review"

    def get(self, request, workspace_id, resource_id):
        rows = get_provenance_service().access_review(workspace_id=workspace_id, resource_id=resource_id)
        return Response({"success": True, "data": AccessReviewResource.from_rows(rows).to_dict()})


class HallTreeView(_BaseProvenanceView):
    name = "provenance-hall-tree"

    def get(self, request, workspace_id, actor_id):
        query = HallTreeQueryRequest.from_query_params(request.query_params)
        result = get_provenance_service().hall_tree(
            workspace_id=workspace_id, actor_id=actor_id, since=query.since, max_depth=query.max_depth
        )
        if result is None:
            return Response({"success": False, "error": "actor not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": HallTreeResource.from_result(result).to_dict()})


class LeastPrivilegeView(_BaseProvenanceView):
    name = "provenance-least-privilege"

    def get(self, request, workspace_id):
        query = LeastPrivilegeQueryRequest.from_query_params(request.query_params)
        gaps = get_provenance_service().least_privilege_gaps(workspace_id=workspace_id, unused_days=query.unused_days)
        return Response({"success": True, "data": LeastPrivilegeResource.from_gaps(gaps).to_dict()})
