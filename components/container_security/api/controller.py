"""Container-security REST surface — the on-demand scan trigger (ADR 0006).

Thin controller: authorize → validate the untrusted image ref → enqueue the scan →
202. The scan runs as the ``scanning.run_scan`` Celery task (async, isolated, retryable),
which renders an ephemeral Trivy Job via the ScanExecutionBackend and emits
FindingObserved → the findings SSOT. Mirrors the cloud_posture "scan now" pattern.
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

_SOURCE = "container_security.trivy"


class ContainerScanView(APIView):
    """POST /container-security/workspaces/<ws>/scan/ — kick off a Trivy image scan."""

    name = "container-security-scan"
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, workspace_id):
        from components.container_security.api.requests.scan_request import ContainerScanRequest
        from components.container_security.api.resources.scan_resource import ContainerScanResource
        from components.container_security.domain.image_reference import (
            InvalidImageReferenceError,
            validate_image_reference,
        )
        from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan
        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )
        from components.shared_platform.application.providers.workspace_access_provider import (
            get_workspace_access_adapter,
        )

        user = request.user
        is_member = (
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or str(workspace_id) in get_workspace_access_adapter().accessible_workspace_ids(user_id=user.id)
        )
        if not is_member:
            return Response({"success": False, "error": "forbidden"}, status=403)
        if not get_feature_flags_provider().is_feature_enabled("feature.container_security", workspace_id=workspace_id):
            return Response({"success": False, "error": "feature_disabled"}, status=403)

        req = ContainerScanRequest.from_data(request.data)
        try:
            image = validate_image_reference(req.image, allowed_registries=req.allowed_registries)
        except InvalidImageReferenceError as exc:
            return Response({"success": False, "error": "invalid_image", "detail": str(exc)}, status=400)

        result = dispatch_scan(
            source=_SOURCE,
            workspace_id=str(workspace_id),
            target_ref=image,
            connection_id=req.connection_id,
            account_id=req.account_id,
            params=req.params,
        )
        resource = ContainerScanResource(task_id=result.id, image=image, source=_SOURCE)
        return Response({"success": True, "data": resource.to_dict()}, status=202)
