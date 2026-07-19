"""REST controller for the unified sign-off queue (Phase 6a).

Thin primary adapter: parse the request, resolve the kernel queue service from
its provider, enforce workspace membership, call the service, serialise. All
orchestration (fan-out, risk gate, delegation, audit) lives in the kernel — the
controller never touches a concrete adapter or a foreign context's ORM.

Endpoints:
  GET  /sign-off/pending/?workspace_id=<id>            merged pending queue
  GET  /sign-off/<artifact_type>/<artifact_id>/        full detail + receipts
  POST /sign-off/<artifact_type>/<artifact_id>/approve/
  POST /sign-off/<artifact_type>/<artifact_id>/request-changes/
  POST /sign-off/<artifact_type>/<artifact_id>/reject/

``SignOffError`` / ``NotApprovedError`` / ``UnregisteredArtifactError`` /
``NotFoundError`` propagate to the shared exception handler, which maps them to
400 / 409 / 404 respectively.
"""

from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from components.sign_off.api.requests.sign_off_decision_request import (
    ApproveRequest,
    ReviewDecisionRequest,
)
from components.sign_off.api.resources.sign_off_resource import (
    SignOffDetailResource,
    SignOffItemResource,
)
from components.sign_off.application.providers.sign_off_queue_provider import (
    get_sign_off_queue_provider,
)


def _is_member(user, workspace_id: str | None) -> bool:
    """True if ``user`` may act on artifacts in ``workspace_id``.

    Reuses the workspace context's membership resolution so the sign-off queue
    honours the same owner/member/team rule as every other workspace surface.
    """
    if user is None or not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    if not workspace_id:
        return False
    from components.workspace.api.permissions import IsOrgOwnerOrMember
    from components.workspace.application.providers.workspaces_models_provider import (
        get_workspaces_models_provider,
    )

    Workspace = get_workspaces_models_provider().Workspace
    workspace = Workspace.objects.filter(id=workspace_id).first()
    if workspace is None:
        return False
    return IsOrgOwnerOrMember()._is_member(user, workspace)


class SignOffPendingView(APIView):
    """GET the merged pending-sign-off queue for a workspace."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            raise ValidationError({"workspace_id": "This query parameter is required."})
        if not _is_member(request.user, workspace_id):
            raise PermissionDenied("You must belong to the workspace to view its sign-off queue.")

        items = get_sign_off_queue_provider().build_service().list_pending(workspace_id)
        data = [SignOffItemResource.from_item(item) for item in items]

        paginator = api_settings.DEFAULT_PAGINATION_CLASS()
        page = paginator.paginate_queryset(data, request, view=self)
        if page is not None:
            return paginator.get_paginated_response(page)
        return Response(data)


class _ArtifactScopedView(APIView):
    """Shared membership resolution for the per-artifact endpoints — the
    workspace comes from the artifact itself (via the kernel), then the same
    member rule is applied."""

    permission_classes = (permissions.IsAuthenticated,)

    def _service_and_guard(self, request, artifact_type: str, artifact_id: str):
        service = get_sign_off_queue_provider().build_service()
        # Raises UnregisteredArtifactError (-> 404) for an unknown type and
        # NotFoundError (-> 404) for an unknown id.
        workspace_id = service.workspace_id(artifact_type, artifact_id)
        if not _is_member(request.user, workspace_id):
            raise PermissionDenied("You must belong to the workspace to review this artifact.")
        return service


class SignOffDetailView(_ArtifactScopedView):
    """GET a single artifact's full detail (state, band, target, receipts)."""

    def get(self, request, artifact_type: str, artifact_id: str):
        service = self._service_and_guard(request, artifact_type, artifact_id)
        detail = service.detail(artifact_type, artifact_id)
        return Response(SignOffDetailResource.from_detail(detail))


class SignOffApproveView(_ArtifactScopedView):
    def post(self, request, artifact_type: str, artifact_id: str):
        service = self._service_and_guard(request, artifact_type, artifact_id)
        payload = ApproveRequest.from_request(request.data)
        service.approve(
            artifact_type,
            artifact_id,
            actor_id=str(request.user.id),
            override_reason=payload.override_reason,
        )
        return Response({"status": "approved"}, status=status.HTTP_200_OK)


class SignOffRequestChangesView(_ArtifactScopedView):
    def post(self, request, artifact_type: str, artifact_id: str):
        service = self._service_and_guard(request, artifact_type, artifact_id)
        payload = ReviewDecisionRequest.from_request(request.data)
        service.request_changes(
            artifact_type,
            artifact_id,
            actor_id=str(request.user.id),
            codes=payload.codes,
            note=payload.note,
        )
        return Response({"status": "changes_requested"}, status=status.HTTP_200_OK)


class SignOffRejectView(_ArtifactScopedView):
    def post(self, request, artifact_type: str, artifact_id: str):
        service = self._service_and_guard(request, artifact_type, artifact_id)
        payload = ReviewDecisionRequest.from_request(request.data)
        service.reject(
            artifact_type,
            artifact_id,
            actor_id=str(request.user.id),
            codes=payload.codes,
            note=payload.note,
        )
        return Response({"status": "rejected"}, status=status.HTTP_200_OK)
