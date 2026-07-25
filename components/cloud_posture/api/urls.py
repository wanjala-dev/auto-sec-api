"""Cloud-posture routes — the CSPM read surface. Mounted at ``/cloud-posture/``."""

from django.urls import path

from components.cloud_posture.api.controller import PostureFindingsView, PostureSummaryView

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/summary/",
        PostureSummaryView.as_view(),
        name=PostureSummaryView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/findings/",
        PostureFindingsView.as_view(),
        name=PostureFindingsView.name,
    ),
]
