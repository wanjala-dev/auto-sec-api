"""Tag vocabulary API routes (ADR 0015 D6)."""

from __future__ import annotations

from django.urls import path

from components.tagging.api.controller import TagDetailView, TagListCreateView

urlpatterns = [
    path("workspaces/<uuid:workspace_id>/tags/", TagListCreateView.as_view(), name="tagging-tags"),
    path(
        "workspaces/<uuid:workspace_id>/tags/<uuid:tag_id>/",
        TagDetailView.as_view(),
        name="tagging-tag-detail",
    ),
]
