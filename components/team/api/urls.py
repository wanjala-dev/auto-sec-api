"""URL configuration for the team bounded context.

Team CRUD, activation, and workspace-scoped team queries.

Invitation and membership routes have been extracted to
``components.membership.api.urls`` (mounted at /membership/).
"""

from django.urls import path

from components.team.api.controller import (
    TeamActivateView,
    TeamAddByUuidView,
    TeamAddView,
    TeamByWorkspaceNameView,
    TeamView,
    WorkspaceActivateView,
)

app_name = "team"


urlpatterns = [
    path("", TeamAddView.as_view(), name=TeamAddView.name),
    path("activate/", TeamActivateView.as_view(), name=TeamActivateView.name),
    path(
        "workspace/activate/",
        WorkspaceActivateView.as_view(),
        name=WorkspaceActivateView.name,
    ),
    path("<int:team_id>/team", TeamView.as_view(), name=TeamView.name),
    path(
        "workspaces/<str:workspace_id>/teams/<str:team_name>",
        TeamByWorkspaceNameView.as_view(),
        name=TeamView.name,
    ),
    path("workspaces/<str:workspace_id>/teams/", TeamView.as_view(), name=TeamView.name),
    path("<str:uuid>/", TeamAddByUuidView.as_view()),
]
