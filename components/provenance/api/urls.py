from django.urls import path

from components.provenance.api.controller import (
    AccessReviewView,
    HallTreeView,
    LeastPrivilegeView,
    VendorBlastRadiusView,
)

urlpatterns = [
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
