"""EVALUATE routes. Mounted at ``/evaluation/`` by ``api/urls.py``.

Every path carries ``workspace_id`` so the permission check has something to
check against. A workspace named in a query param or a body cannot be guarded
by a URL-scoped permission class — that was the shape of #450.
"""

from __future__ import annotations

from django.urls import path

from components.evaluation.api.controller import (
    EvalEstimateView,
    EvalProvenanceView,
    EvalRunCreateView,
    EvalRunDetailView,
    EvalRunListView,
    EvalSuiteListView,
)

app_name = "evaluation"

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/suites/", EvalSuiteListView.as_view(), name="eval-suites"),
    path(
        "workspaces/<uuid:workspace_id>/suites/<uuid:suite_id>/estimate/",
        EvalEstimateView.as_view(),
        name="eval-estimate",
    ),
    path(
        "workspaces/<uuid:workspace_id>/suites/<uuid:suite_id>/runs/",
        EvalRunCreateView.as_view(),
        name="eval-run-create",
    ),
    path("workspaces/<uuid:workspace_id>/runs/", EvalRunListView.as_view(), name="eval-runs"),
    path(
        "workspaces/<uuid:workspace_id>/runs/<uuid:run_id>/",
        EvalRunDetailView.as_view(),
        name="eval-run-detail",
    ),
    path(
        "workspaces/<uuid:workspace_id>/results/<uuid:result_id>/provenance/",
        EvalProvenanceView.as_view(),
        name="eval-provenance",
    ),
]
