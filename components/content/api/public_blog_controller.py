"""Public (unauthenticated) read endpoints for PUBLISHED blog posts.

Surfaces ``WritingDraft`` blogs (``kind='blog'``, ``status='published'``)
for a workspace to anonymous callers. The marketing landing site
(www.octopusintl.org) calls these to display blogs that were authored in
the app's own Writing surface — i.e. we dogfood our Content product to
power the marketing blog.

Read-only. No auth, no write. The blog ``slug`` is derived from the title
(``slugify``) so the landing can route ``/blog/<slug>`` without a schema
change. Detail lookup matches on that derived slug.

Only ``status='published'`` blogs are ever returned — drafts stay private.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from django.utils.text import slugify
from rest_framework import status as http_status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from components.content.application.providers.writing_draft_repository_provider import (
    get_writing_draft_repository_provider,
)
from components.content.domain.enums import WritingDraftKind, WritingDraftStatus

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _excerpt(body_html: str, limit: int = 200) -> str:
    """Plain-text teaser from the HTML body for list cards / meta description."""
    text = _TAG_RE.sub(" ", body_html or "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _serialize(entity, *, full: bool) -> dict:
    meta = entity.metadata or {}
    data = {
        "id": str(entity.id),
        "slug": slugify(entity.title),
        "title": entity.title,
        "excerpt": _excerpt(entity.body_html),
        # Optional cover image (a URL/path the landing renders as the post
        # hero + OG image). Stored in metadata so no schema change; the
        # landing falls back to a typographic cover when absent.
        "cover_image": meta.get("cover_image") or None,
        "published_at": entity.updated_at.isoformat() if entity.updated_at else None,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
    }
    if full:
        data["body_html"] = entity.body_html
    return data


def _published_blogs(workspace_id: UUID):
    repo = get_writing_draft_repository_provider().repository()
    return repo.list_for_workspace(
        workspace_id=workspace_id,
        kind=WritingDraftKind.BLOG,
        status=WritingDraftStatus.PUBLISHED,
        limit=100,
        offset=0,
    )


class PublicBlogListView(APIView):
    """GET published blogs for a workspace. Anonymous, read-only."""

    name = "public-blog-list"
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request, workspace_id):
        items = _published_blogs(workspace_id)
        return Response({"results": [_serialize(i, full=False) for i in items]})


class PublicBlogDetailView(APIView):
    """GET one published blog by its title-derived slug. Anonymous."""

    name = "public-blog-detail"
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request, workspace_id, slug):
        match = next(
            (i for i in _published_blogs(workspace_id) if slugify(i.title) == slug),
            None,
        )
        if match is None:
            return Response(
                {"detail": "Blog not found"},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(_serialize(match, full=True))
