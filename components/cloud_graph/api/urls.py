"""Cloud asset graph read API routes."""

from __future__ import annotations

from django.urls import path

from components.cloud_graph.api.controller import (
    AssetGraphView,
    AttackPathListView,
    ExposureSummaryView,
    RiskScoreView,
)

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/graph/", AssetGraphView.as_view(), name="cloud-graph-asset-graph"),
    path(
        "workspaces/<uuid:workspace_id>/attack-paths/",
        AttackPathListView.as_view(),
        name="cloud-graph-attack-paths",
    ),
    path(
        "workspaces/<uuid:workspace_id>/risk-score/",
        RiskScoreView.as_view(),
        name="cloud-graph-risk-score",
    ),
    path(
        "workspaces/<uuid:workspace_id>/exposure-summary/",
        ExposureSummaryView.as_view(),
        name="cloud-graph-exposure-summary",
    ),
]
