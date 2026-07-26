"""Container-security routes — the SCA scan surface. Mounted at ``/container-security/``."""

from django.urls import path

from components.container_security.api.controller import ContainerScanView

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/scan/",
        ContainerScanView.as_view(),
        name=ContainerScanView.name,
    ),
]
