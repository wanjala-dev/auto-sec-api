"""HTTP surface for reversible SOC response actions (ADR 0005 / roadmap #5).

Thin: parse → call ``ResponseActionService`` → map domain errors to status codes.
The *approval* and *rollback* endpoints are the human-in-the-loop gate — they run
the irreversible cloud mutation, so they are the ONLY path that executes (the agent
tool can only propose). Reads (list/detail) are membership-scoped; every lifecycle
mutation (propose/approve/reject/rollback) additionally requires the
``manage_cases`` capability, so read-only viewer roles cannot drive response
actions. No business logic, no ORM, no boto3 here.
"""

from __future__ import annotations

from uuid import UUID

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from components.membership.api.permissions import has_workspace_permission
from components.response.api.resources.response_action_resource import ResponseActionResource
from components.response.domain.errors import (
    IllegalTransitionError,
    ResponseActionError,
    ResponseActionNotFoundError,
    UnsafeActionError,
)
from components.response.infrastructure.services.workspace_access import is_workspace_member


def _forbidden():
    return Response({"success": False, "error": "forbidden"}, status=403)


# Capability gate for the response-action lifecycle mutations. Owners pass
# structurally; admin/member roles carry ``manage_cases``; the read-only viewer
# role does not — mirroring the ``CanManageIntegrations`` pattern in integrations.
CanManageCases = has_workspace_permission("manage_cases")


def _error_response(exc: Exception):
    if isinstance(exc, ResponseActionNotFoundError):
        return Response({"success": False, "error": "not_found"}, status=404)
    if isinstance(exc, IllegalTransitionError):
        return Response({"success": False, "error": str(exc)}, status=409)
    if isinstance(exc, UnsafeActionError):
        return Response({"success": False, "error": str(exc)}, status=422)
    if isinstance(exc, ResponseActionError):
        return Response({"success": False, "error": str(exc)}, status=400)
    raise exc


class ResponseActionProposeView(APIView):
    """POST /response/workspaces/<ws>/actions/propose/ — record a proposal (no cloud effect).

    Grounds the proposed revoke against the live security group before persisting;
    the returned action is PROPOSED, awaiting a human approve. Dry-run defaults to
    ``SOC_RESPONSE_DRY_RUN_DEFAULT`` (True) so the demo never mutates until a real
    execution is deliberately enabled.
    """

    permission_classes = (permissions.IsAuthenticated, CanManageCases)

    def post(self, request, workspace_id):
        from django.conf import settings

        from components.response.api.requests.propose_response_action_request import (
            ProposeRequestError,
            ProposeResponseActionRequest,
        )
        from components.response.application.providers.response_provider import build_response_service

        try:
            req = ProposeResponseActionRequest.from_request(
                request.data,
                default_dry_run=bool(getattr(settings, "SOC_RESPONSE_DRY_RUN_DEFAULT", True)),
            )
        except ProposeRequestError as exc:
            return Response({"success": False, "error": str(exc)}, status=400)

        try:
            action = build_response_service().propose(
                workspace_id=UUID(str(workspace_id)),
                finding_fingerprint=req.finding_fingerprint,
                spec=req.spec,
                requested_by=str(request.user.id),
                dry_run=req.dry_run,
            )
        except Exception as exc:
            return _error_response(exc)
        return Response({"success": True, "data": ResponseActionResource.one(action)}, status=201)


class ResponseActionListView(APIView):
    """GET /response/workspaces/<ws>/actions/?status= — list actions (newest first)."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id):
        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return _forbidden()
        from components.response.application.providers.response_provider import build_response_service

        status = request.query_params.get("status") or None
        actions = build_response_service().list_for_workspace(workspace_id=UUID(str(workspace_id)), status=status)
        return Response({"success": True, "data": ResponseActionResource.many(actions)})


class ResponseActionDetailView(APIView):
    """GET /response/workspaces/<ws>/actions/<id>/ — one action."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id, action_id):
        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return _forbidden()
        from components.response.application.providers.response_provider import build_response_service

        action = build_response_service().get(action_id=UUID(str(action_id)), workspace_id=UUID(str(workspace_id)))
        if action is None:
            return Response({"success": False, "error": "not_found"}, status=404)
        return Response({"success": True, "data": ResponseActionResource.one(action)})


class ResponseActionApproveView(APIView):
    """POST /response/workspaces/<ws>/actions/<id>/approve/ — human approves + executes."""

    permission_classes = (permissions.IsAuthenticated, CanManageCases)

    def post(self, request, workspace_id, action_id):
        from components.response.application.providers.response_provider import build_response_service

        try:
            action = build_response_service().approve(
                action_id=UUID(str(action_id)),
                workspace_id=UUID(str(workspace_id)),
                approver_id=str(request.user.id),
                justification=str(request.data.get("justification") or ""),
            )
        except Exception as exc:
            return _error_response(exc)
        return Response({"success": True, "data": ResponseActionResource.one(action)})


class ResponseActionRejectView(APIView):
    """POST /response/workspaces/<ws>/actions/<id>/reject/ — human declines."""

    permission_classes = (permissions.IsAuthenticated, CanManageCases)

    def post(self, request, workspace_id, action_id):
        from components.response.application.providers.response_provider import build_response_service

        try:
            action = build_response_service().reject(
                action_id=UUID(str(action_id)),
                workspace_id=UUID(str(workspace_id)),
                actor_id=str(request.user.id),
                note=str(request.data.get("note") or ""),
            )
        except Exception as exc:
            return _error_response(exc)
        return Response({"success": True, "data": ResponseActionResource.one(action)})


class ResponseActionRollbackView(APIView):
    """POST /response/workspaces/<ws>/actions/<id>/rollback/ — undo an executed action."""

    permission_classes = (permissions.IsAuthenticated, CanManageCases)

    def post(self, request, workspace_id, action_id):
        from components.response.application.providers.response_provider import build_response_service

        try:
            action = build_response_service().rollback(
                action_id=UUID(str(action_id)),
                workspace_id=UUID(str(workspace_id)),
                actor_id=str(request.user.id),
            )
        except Exception as exc:
            return _error_response(exc)
        return Response({"success": True, "data": ResponseActionResource.one(action)})
