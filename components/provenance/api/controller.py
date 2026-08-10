"""REST surface for the provenance/access graph (read-only, workspace-scoped).

Thin primary adapter: parse the request, call the application service through
its provider, wrap the result in a resource DTO. Gated by
``feature.provenance_graph`` and active workspace membership. No business logic,
no ORM.
"""

from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from components.provenance.api.requests.agent_telemetry_requests import (
    AgentTelemetryIngestRequest,
    AgentTelemetryRequestError,
    PayloadTooLargeError,
)
from components.provenance.api.requests.graph_requests import (
    HallTreeQueryRequest,
    LeastPrivilegeQueryRequest,
)
from components.provenance.api.resources.agent_telemetry_resources import AgentTelemetryIngestResource
from components.provenance.api.resources.graph_resources import (
    AccessReviewResource,
    BlastRadiusResource,
    GraphOverviewResource,
    HallTreeResource,
    LeastPrivilegeResource,
)
from components.provenance.application.providers.agent_telemetry_provider import (
    FEATURE_FLAG as AGENT_TELEMETRY_FLAG,
)
from components.provenance.application.providers.agent_telemetry_provider import (
    get_ingest_agent_telemetry_use_case,
)
from components.provenance.application.providers.provenance_provider import get_provenance_service
from components.provenance.domain.errors import (
    AgentTelemetryContentRejectedError,
    AgentTelemetryPayloadError,
    AgentTelemetrySourceUnavailableError,
    UnsupportedAgentTelemetryKindError,
)
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


class AgentTelemetryIngestView(APIView):
    """Ingest one batch of a workspace's OWN agent-runtime telemetry (ADR 0023).

    The write half of the provenance context, and the only one: it appends to the
    existing graph and creates no new store. Gated by its own dark flag
    (``feature.agent_runtime_accountability``) — a **sibling** of
    ``feature.provenance_graph``, never a reuse, because opting into the internal
    access graph is not consent to observe your agents. Reading the rows back
    through the graph API still needs ``feature.provenance_graph``, which is dark
    today; un-darkening it is a separate, deliberate decision (ADR 0023 §6).

    Consent lives on the ``AgentTelemetrySource`` row addressed by ``source_id``:
    the agent allowlist is enforced there, fail-closed, and a source id belonging
    to another workspace simply does not resolve.

    **Metadata-only.** A payload carrying prompt or tool-argument content is
    refused with 422 rather than stripped — see
    ``AgentTelemetryContentRejectedError`` for the reasoning.

    Authenticated with the platform's normal JWT + active workspace membership,
    which is what a customer script POSTs with today. A Vercel Trace Drain — which
    cannot present a user JWT — plugs in later behind a drain-token authenticator
    on this same route and the same adapter; the ledger below does not move.

    ⚠ Attribution here is a join WE perform, never a field we read. No telemetry
    standard carries a principal or credential attribute, and Stripe does not
    expose the acting API key per request programmatically. Records are
    **attributable**, not proven.
    """

    name = "provenance-agent-telemetry-ingest"
    permission_classes = (permissions.IsAuthenticated, HasWorkspaceMembership, RequiresFeatureFlag)
    feature_flag_key = AGENT_TELEMETRY_FLAG
    throttle_scope = "agent_telemetry_ingest"
    throttle_classes = (ScopedRateThrottle,)

    def post(self, request, workspace_id, source_id):
        try:
            parsed = AgentTelemetryIngestRequest.from_request(request)
        except PayloadTooLargeError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        except AgentTelemetryRequestError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = get_ingest_agent_telemetry_use_case().execute(
                workspace_id=workspace_id,
                source_id=source_id,
                payload=parsed.payload,
            )
        except AgentTelemetrySourceUnavailableError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except UnsupportedAgentTelemetryKindError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_501_NOT_IMPLEMENTED)
        except AgentTelemetryContentRejectedError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except AgentTelemetryPayloadError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"success": True, "data": AgentTelemetryIngestResource.from_result(result).to_dict()},
            status=status.HTTP_202_ACCEPTED,
        )
