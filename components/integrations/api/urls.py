"""Integrations routes — AWS Organization onboarding. Mounted at /integrations/."""

from django.urls import path

from components.integrations.api.controller import (
    AwsConnectionLogStreamView,
    AwsConnectionListCreateView,
    AwsConnectionTemplateView,
    AwsConnectionVerifyView,
)

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/aws/",
        AwsConnectionListCreateView.as_view(),
        name=AwsConnectionListCreateView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/aws/<uuid:connection_id>/cloudformation/",
        AwsConnectionTemplateView.as_view(),
        name=AwsConnectionTemplateView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/aws/<uuid:connection_id>/verify/",
        AwsConnectionVerifyView.as_view(),
        name=AwsConnectionVerifyView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/aws/<uuid:connection_id>/logstream/",
        AwsConnectionLogStreamView.as_view(),
        name=AwsConnectionLogStreamView.name,
    ),
]
