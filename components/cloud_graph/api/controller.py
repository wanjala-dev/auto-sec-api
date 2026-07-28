"""Read API for the cloud asset graph. Thin, membership-gated, ORM-free.

Makes the CNAPP asset graph (ADR 0004 / ADR 0005) visible to the HUD: a workspace's
cloud-resource nodes (exposure-typed) + the typed edges among them — the read surface
the Asset Graph panel renders. Read-only; the graph is populated by the cloud_graph
sync detector (owner-persists), never here.
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


class AssetGraphView(APIView):
    """GET /cloud-graph/workspaces/<ws>/graph/?exposure=&resource_type=&limit= — nodes+edges."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "cloud-graph-asset-graph"

    def get(self, request, workspace_id):
        from components.cloud_graph.api.requests.get_asset_graph_request import GetAssetGraphRequest
        from components.cloud_graph.api.resources.asset_graph_resource import AssetGraphResource
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.cloud_graph.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        req = GetAssetGraphRequest.from_request(request, workspace_id)
        view = CloudGraphProvider.build_get_asset_graph_use_case().execute(req.to_query())
        return Response({"success": True, "data": AssetGraphResource.graph(view)})


class AttackPathListView(APIView):
    """GET /cloud-graph/workspaces/<ws>/attack-paths/?category=&min_score=&limit= — ranked paths."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "cloud-graph-attack-paths"

    def get(self, request, workspace_id):
        from components.cloud_graph.api.requests.list_attack_paths_request import ListAttackPathsRequest
        from components.cloud_graph.api.resources.attack_path_resource import AttackPathResource
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.cloud_graph.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        req = ListAttackPathsRequest.from_request(request, workspace_id)
        paths = CloudGraphProvider.build_list_attack_paths_use_case().execute(req.to_query())
        return Response({"success": True, "data": AttackPathResource.collection(paths)})


class RiskScoreView(APIView):
    """GET /cloud-graph/workspaces/<ws>/risk-score/ — one opinionated, attack-path-led risk score.

    The centerpiece the HUD gauge reads: value (0–100 risk) + posture (100-value) + the factor
    breakdown of what drives it. Read-only rollup over findings + attack paths.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "cloud-graph-risk-score"

    def get(self, request, workspace_id):
        from components.cloud_graph.api.resources.risk_score_resource import RiskScoreResource
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.cloud_graph.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        score = CloudGraphProvider.build_get_risk_score_use_case().execute(workspace_id)
        return Response({"success": True, "data": RiskScoreResource.of(score)})


class ExposureSummaryView(APIView):
    """GET /cloud-graph/workspaces/<ws>/exposure-summary/ — the cloud attack-surface +
    asset-inventory rollup the HUD's Attack-Surface / Asset cards read.

    Real counts only: assets by exposure + type, internet-exposed assets carrying an open
    critical/high finding (correlated by asset_urn), and the live attack-path count.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "cloud-graph-exposure-summary"

    def get(self, request, workspace_id):
        from components.cloud_graph.api.resources.exposure_summary_resource import ExposureSummaryResource
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.cloud_graph.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        summary = CloudGraphProvider.build_get_exposure_summary_use_case().execute(workspace_id)
        return Response({"success": True, "data": ExposureSummaryResource.of(summary)})
