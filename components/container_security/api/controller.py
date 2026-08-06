"""Container-security REST surface — the on-demand scan trigger + SBOM read (ADR 0006).

Thin controllers: authorize → call the use case → respond. The scan runs as the
``scanning.run_scan`` Celery task (async, isolated, retryable), which renders an
ephemeral Trivy Job via the ScanExecutionBackend and emits FindingObserved → the
findings SSOT. Mirrors the cloud_posture "scan now" pattern. The SBOM endpoint
(task #99 P1) returns the stored CycloneDX SBOM's metadata + presigned URLs — the
body itself is fetched straight from the object store by the browser.
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

_SOURCE = "container_security.trivy"


def _is_workspace_member(user, workspace_id) -> bool:
    from components.shared_platform.application.providers.workspace_access_provider import (
        get_workspace_access_adapter,
    )

    return (
        getattr(user, "is_staff", False)
        or getattr(user, "is_superuser", False)
        or str(workspace_id) in get_workspace_access_adapter().accessible_workspace_ids(user_id=user.id)
    )


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

        if not _is_workspace_member(request.user, workspace_id):
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


class ContainerScanSbomView(APIView):
    """GET /container-security/workspaces/<ws>/scans/<scan_run_id>/sbom/ — the scan's SBOM.

    Metadata + presigned URLs only (``fetch_url`` for the HUD's client-side package
    list, ``download_url`` with attachment disposition); the body never transits the
    API. 404 ``sbom_not_available`` is the honest absent state (SBOM pass failed, or
    a pre-SBOM scan).
    """

    name = "container-security-scan-sbom"
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id, scan_run_id):
        from components.container_security.api.resources.sbom_resource import ImageSbomResource
        from components.container_security.application.providers.sbom_provider import (
            build_get_image_sbom_use_case,
        )
        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )

        if not _is_workspace_member(request.user, workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)
        if not get_feature_flags_provider().is_feature_enabled("feature.container_security", workspace_id=workspace_id):
            return Response({"success": False, "error": "feature_disabled"}, status=403)

        view = build_get_image_sbom_use_case().execute(workspace_id=workspace_id, scan_run_id=scan_run_id)
        if view is None:
            return Response({"success": False, "error": "sbom_not_available"}, status=404)
        return Response({"success": True, "data": ImageSbomResource.from_view(view).to_dict()})
