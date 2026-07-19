"""Views for WritingTemplate read + CRUD."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.content.api.permissions import (
    CanManageTemplates,
    CanReadWriting,
)
from components.content.domain.errors import WritingTemplateNotFoundError

logger = logging.getLogger(__name__)


def _serialize(entity) -> dict[str, Any]:
    metadata = getattr(entity, "metadata", {}) or {}
    return {
        "id": str(entity.id),
        "name": entity.name,
        "description": entity.description,
        "kind": entity.kind,
        "body_html": entity.body_html,
        # ``layout`` is the block-tree design (newsletter design templates) so
        # the gallery can render a real visual preview, not just the prose
        # body_html. None for prose templates.
        "layout": metadata.get("layout"),
        "is_seeded": entity.is_seeded,
        "workspace_id": str(entity.workspace_id) if entity.workspace_id else None,
        "created_at": entity.created_at.isoformat(),
        "updated_at": entity.updated_at.isoformat(),
    }


class WritingTemplateListView(APIView):
    """GET lists templates, POST creates a new workspace-owned template."""

    name = "writing-template-list"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [CanReadWriting()]
        return [CanManageTemplates()]

    def get(self, request):
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "workspace_id query param required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from components.content.application.providers.writing_template_repository_provider import (
            get_writing_template_repository_provider,
        )

        items = get_writing_template_repository_provider().repository().list_available(
            workspace_id=UUID(workspace_id),
            kind=request.query_params.get("kind"),
        )
        return Response({"results": [_serialize(i) for i in items]})

    def post(self, request):
        name = request.data.get("name")
        kind = request.data.get("kind")
        if not all([name, kind]):
            return Response(
                {"detail": "name and kind required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from components.content.application.providers.writing_template_repository_provider import (
            get_writing_template_repository_provider,
        )

        workspace_id_raw = request.data.get("workspace_id")
        workspace_id = UUID(workspace_id_raw) if workspace_id_raw else None
        try:
            entity = get_writing_template_repository_provider().repository().create(
                name=name,
                description=request.data.get("description", ""),
                kind=kind,
                body_html=request.data.get("body_html", ""),
                is_seeded=False,
                workspace_id=workspace_id,
                metadata=request.data.get("metadata", {}),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize(entity), status=status.HTTP_201_CREATED)


class WritingTemplateDetailView(APIView):
    """GET reads a template, PATCH edits it, DELETE removes it."""

    name = "writing-template-detail"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [CanReadWriting()]
        return [CanManageTemplates()]

    def get(self, request, template_id: UUID):
        from components.content.application.providers.writing_template_repository_provider import (
            get_writing_template_repository_provider,
        )

        entity = get_writing_template_repository_provider().repository().get(template_id=template_id)
        if entity is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(entity))

    def patch(self, request, template_id: UUID):
        from components.content.application.providers.writing_template_repository_provider import (
            get_writing_template_repository_provider,
        )

        try:
            entity = get_writing_template_repository_provider().repository().update(
                template_id=template_id,
                name=request.data.get("name", ""),
                description=request.data.get("description", ""),
                body_html=request.data.get("body_html", ""),
            )
        except WritingTemplateNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(entity))

    def delete(self, request, template_id: UUID):
        from components.content.application.providers.writing_template_repository_provider import (
            get_writing_template_repository_provider,
        )

        get_writing_template_repository_provider().repository().delete(template_id=template_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WritingTemplateRenderView(APIView):
    """Return the template body with workspace-derived placeholders resolved.

    Used by the templates list preview drawer so the user sees real
    values for the workspace they're in (``{{donations_total}}`` →
    ``$435`` etc) instead of the literal tokens. The resolver is the
    same one ``CreateWritingDraftUseCase`` invokes when a draft is
    seeded from this template, so the preview matches what the user
    will land in once they click "Use this template".

    Read-only: does not create a draft, does not mutate the template.
    Gate ``view_writing`` because rendering reveals workspace metrics —
    it's a read operation even though it's a POST.
    """

    permission_classes = (CanReadWriting,)
    name = "writing-template-render"

    def post(self, request, template_id: UUID):
        workspace_id_raw = request.data.get("workspace_id")
        if not workspace_id_raw:
            return Response(
                {"detail": "workspace_id required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            workspace_id = UUID(workspace_id_raw)
        except (ValueError, TypeError):
            return Response(
                {"detail": "workspace_id must be a UUID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from components.content.application.providers.template_placeholder_provider import (
            get_template_placeholder_provider,
        )
        from components.content.application.providers.writing_template_repository_provider import (
            get_writing_template_repository_provider,
        )

        template = get_writing_template_repository_provider().repository().get(template_id=template_id)
        if template is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        resolver = get_template_placeholder_provider().resolver()
        rendered = resolver.resolve(
            body_html=template.body_html or "",
            workspace_id=workspace_id,
        )

        # Design templates (kind=newsletter) carry a block-tree ``layout`` in
        # metadata. Resolve its tokens too — KPI cards fill with the workspace's
        # real figures and the donate CTA points at the public donate page — so
        # the gallery preview shows the true render, not literal {{tokens}}.
        resolved_layout = None
        layout = (getattr(template, "metadata", None) or {}).get("layout")
        if isinstance(layout, dict) and layout.get("blocks"):
            from components.content.api.newsletter_controller import (
                _resolve_layout_placeholders,
            )

            donate_url = ""
            try:
                from components.content.application.use_cases.generate_newsletter_use_case import (
                    _workspace_donate_url,
                )

                donate_url = _workspace_donate_url(workspace_id) or ""
            except Exception:  # noqa: BLE001 — link is best-effort
                logger.exception(
                    "template render donate-url resolve failed workspace_id=%s",
                    workspace_id,
                )
            resolved_layout = _resolve_layout_placeholders(
                layout, resolver, workspace_id, donate_url
            )

        return Response(
            {
                "template_id": str(template.id),
                "workspace_id": str(workspace_id),
                "body_html": rendered,
                "layout": resolved_layout,
            }
        )
