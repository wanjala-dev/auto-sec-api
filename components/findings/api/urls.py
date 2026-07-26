"""Findings read API routes."""

from __future__ import annotations

from django.urls import path

from components.findings.api.controller import FindingListView

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/", FindingListView.as_view(), name="findings-list"),
]
