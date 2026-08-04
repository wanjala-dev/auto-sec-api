"""Findings read API routes."""

from __future__ import annotations

from django.urls import path

from components.findings.api.controller import (
    AttckCoverageView,
    ComplianceSummaryView,
    FindingListView,
    FindingStatusView,
    FindingTagView,
    SampleDataModeView,
)

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/", FindingListView.as_view(), name="findings-list"),
    path(
        "workspaces/<uuid:workspace_id>/<uuid:finding_id>/status/",
        FindingStatusView.as_view(),
        name="findings-status",
    ),
    path(
        "workspaces/<uuid:workspace_id>/<uuid:finding_id>/tags/",
        FindingTagView.as_view(),
        name="findings-tags",
    ),
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
    path(
        "workspaces/<uuid:workspace_id>/sample-data/mode/",
        SampleDataModeView.as_view(),
        name="findings-sample-data-mode",
    ),
]
