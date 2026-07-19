"""Template Kernel URL routing — one file per context."""

from __future__ import annotations

from django.urls import path

from components.templates.api.controller import TemplateGalleryView

urlpatterns = [
    path("", TemplateGalleryView.as_view(), name="template-gallery"),
]
