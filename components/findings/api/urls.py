"""Findings read API routes."""

from __future__ import annotations

from django.urls import path

from components.findings.api.controller import (
    AttckCoverageView,
    ComplianceSummaryView,
    FindingListView,
)

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/", FindingListView.as_view(), name="findings-list"),
    path(
        "workspaces/<uuid:workspace_id>/attack-coverage/",
        AttckCoverageView.as_view(),
        name="findings-attck-coverage",
    ),
    path(
        "workspaces/<uuid:workspace_id>/compliance-summary/",
        ComplianceSummaryView.as_view(),
        name="findings-compliance-summary",
    ),
]
