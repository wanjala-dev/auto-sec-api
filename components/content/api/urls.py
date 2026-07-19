"""Content authoring routes — trimmed to the WRITING / AI-assist surface.

The auto-sec fork keeps the draft authoring + AI-assist path (draft, draft
with AI, assist thread, writing templates). The legacy news/blog controller,
newsletters, subscribers, and public email-compliance routes are nonprofit
surfaces and are NOT mounted here.
"""

from django.urls import path

from components.content.api import ai_draft_controller as ai_draft_views
from components.content.api import draft_controller as draft_views
from components.content.api import template_controller as template_views

urlpatterns = [
    # ── Writing Drafts ──────────────────────────────────────────────
    path(
        "drafts/",
        draft_views.WritingDraftListView.as_view(),
        name=draft_views.WritingDraftListView.name,
    ),
    path(
        "drafts/<uuid:draft_id>/",
        draft_views.WritingDraftDetailView.as_view(),
        name=draft_views.WritingDraftDetailView.name,
    ),
    path(
        "drafts/<uuid:draft_id>/publish/",
        draft_views.WritingDraftPublishView.as_view(),
        name=draft_views.WritingDraftPublishView.name,
    ),
    path(
        "drafts/<uuid:draft_id>/export-pdf/",
        draft_views.WritingDraftExportPdfView.as_view(),
        name=draft_views.WritingDraftExportPdfView.name,
    ),
    path(
        "drafts/<uuid:draft_id>/draft-with-ai/",
        ai_draft_views.WritingDraftAskAiView.as_view(),
        name=ai_draft_views.WritingDraftAskAiView.name,
    ),
    path(
        "drafts/<uuid:draft_id>/assist-thread/",
        ai_draft_views.WritingDraftAssistThreadView.as_view(),
        name=ai_draft_views.WritingDraftAssistThreadView.name,
    ),
    # ── Writing Templates ───────────────────────────────────────────
    path(
        "templates/",
        template_views.WritingTemplateListView.as_view(),
        name=template_views.WritingTemplateListView.name,
    ),
    path(
        "templates/<uuid:template_id>/",
        template_views.WritingTemplateDetailView.as_view(),
        name=template_views.WritingTemplateDetailView.name,
    ),
    path(
        "templates/<uuid:template_id>/render/",
        template_views.WritingTemplateRenderView.as_view(),
        name=template_views.WritingTemplateRenderView.name,
    ),
]
