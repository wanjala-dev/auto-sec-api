"""URL routing for the unified sign-off queue.

Mounted at ``/sign-off/`` by ``api/urls.py``. The ``<artifact_type>`` segment
is a stable kernel identifier (``financial_report`` / ``newsletter`` /
``writing_draft`` / ``workflow_email``); ``<artifact_id>`` is that context's own
row id (a UUID for most, so kept as a permissive ``str``).
"""

from __future__ import annotations

from django.urls import path

from components.sign_off.api.controller import (
    SignOffApproveView,
    SignOffDetailView,
    SignOffPendingView,
    SignOffRejectView,
    SignOffRequestChangesView,
)

urlpatterns = [
    path("pending/", SignOffPendingView.as_view(), name="sign-off-pending"),
    path(
        "<str:artifact_type>/<str:artifact_id>/",
        SignOffDetailView.as_view(),
        name="sign-off-detail",
    ),
    path(
        "<str:artifact_type>/<str:artifact_id>/approve/",
        SignOffApproveView.as_view(),
        name="sign-off-approve",
    ),
    path(
        "<str:artifact_type>/<str:artifact_id>/request-changes/",
        SignOffRequestChangesView.as_view(),
        name="sign-off-request-changes",
    ),
    path(
        "<str:artifact_type>/<str:artifact_id>/reject/",
        SignOffRejectView.as_view(),
        name="sign-off-reject",
    ),
]
