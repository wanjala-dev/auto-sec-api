"""Reversible SOC response-action API routes."""

from __future__ import annotations

from django.urls import path

from components.response.api.controller import (
    ResponseActionApproveView,
    ResponseActionDetailView,
    ResponseActionListView,
    ResponseActionProposeView,
    ResponseActionRejectView,
    ResponseActionRollbackView,
)

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/actions/propose/",
        ResponseActionProposeView.as_view(),
        name="response-action-propose",
    ),
    path(
        "workspaces/<uuid:workspace_id>/actions/",
        ResponseActionListView.as_view(),
        name="response-action-list",
    ),
    path(
        "workspaces/<uuid:workspace_id>/actions/<uuid:action_id>/",
        ResponseActionDetailView.as_view(),
        name="response-action-detail",
    ),
    path(
        "workspaces/<uuid:workspace_id>/actions/<uuid:action_id>/approve/",
        ResponseActionApproveView.as_view(),
        name="response-action-approve",
    ),
    path(
        "workspaces/<uuid:workspace_id>/actions/<uuid:action_id>/reject/",
        ResponseActionRejectView.as_view(),
        name="response-action-reject",
    ),
    path(
        "workspaces/<uuid:workspace_id>/actions/<uuid:action_id>/rollback/",
        ResponseActionRollbackView.as_view(),
        name="response-action-rollback",
    ),
]
