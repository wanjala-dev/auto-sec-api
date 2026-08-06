"""Container-security routes — the SCA scan surface. Mounted at ``/container-security/``."""

from django.urls import path

from components.container_security.api.controller import ContainerScanSbomView, ContainerScanView

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/scan/",
        ContainerScanView.as_view(),
        name=ContainerScanView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/scans/<uuid:scan_run_id>/sbom/",
        ContainerScanSbomView.as_view(),
        name=ContainerScanSbomView.name,
    ),
]
