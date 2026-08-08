"""Code-security routes — the SAST scan surface. Mounted at ``/code-security/``."""

from django.urls import path

from components.code_security.api.controller import (
    RepoScanSnapshotListView,
    RepoScanStatusListView,
    RepoScanView,
)

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/scan/",
        RepoScanView.as_view(),
        name=RepoScanView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/repos/",
        RepoScanStatusListView.as_view(),
        name=RepoScanStatusListView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/snapshots/",
        RepoScanSnapshotListView.as_view(),
        name=RepoScanSnapshotListView.name,
    ),
]
