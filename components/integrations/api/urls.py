"""Integrations routes — AWS Organization onboarding + GitHub draft-PR. Mounted at /integrations/."""

from django.urls import path

from components.integrations.api.controller import (
    AwsConnectionListCreateView,
    AwsConnectionLogStreamView,
    AwsConnectionTemplateView,
    AwsConnectionVerifyView,
    FindingOpenDraftPrView,
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
    path(
        # str, not int/uuid: Task pks are integers today, but the use case
        # validates the id itself and answers a typed finding_not_found —
        # a malformed id must yield that JSON error, not a bare URL 404.
        "workspaces/<uuid:workspace_id>/findings/<str:task_id>/open-draft-pr/",
        FindingOpenDraftPrView.as_view(),
        name=FindingOpenDraftPrView.name,
    ),
]
