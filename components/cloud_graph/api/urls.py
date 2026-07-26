"""Cloud asset graph read API routes."""

from __future__ import annotations

from django.urls import path

from components.cloud_graph.api.controller import AssetGraphView

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/graph/", AssetGraphView.as_view(), name="cloud-graph-asset-graph"),
]
