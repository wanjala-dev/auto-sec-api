from django.urls import path

from components.provenance.api.controller import (
    AccessReviewView,
    AgentTelemetryIngestView,
    GraphOverviewView,
    HallTreeView,
    LeastPrivilegeView,
    VendorBlastRadiusView,
)

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/agent-telemetry/<uuid:source_id>/ingest/",
        AgentTelemetryIngestView.as_view(),
        name=AgentTelemetryIngestView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/graph/",
        GraphOverviewView.as_view(),
        name=GraphOverviewView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/actors/<uuid:actor_id>/blast-radius/",
        VendorBlastRadiusView.as_view(),
        name=VendorBlastRadiusView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/actors/<uuid:actor_id>/hall-tree/",
        HallTreeView.as_view(),
        name=HallTreeView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/resources/<uuid:resource_id>/access-review/",
        AccessReviewView.as_view(),
        name=AccessReviewView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/least-privilege/",
        LeastPrivilegeView.as_view(),
        name=LeastPrivilegeView.name,
    ),
]
