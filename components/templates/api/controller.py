"""Template Kernel REST controller — the unified gallery read.

Thin primary adapter: parses the request, calls the kind registry, returns
normalized ``TemplateSummary`` rows. No business logic, no ORM. One endpoint
serves every kind — the gallery the frontend ``TemplateGallery`` consumes.

Deletion is NOT here: templates are trashed via the shared recycle bin
(``POST /recycle-bin/trash/`` with ``entity_type=<kind_id>``) once a kind's
soft-delete adapter is registered. One bin, one delete path for everything.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from components.shared_platform.api.permissions import HasWorkspaceMembership
from components.templates.api.requests.template_gallery_request import TemplateGalleryRequest
from components.templates.api.resources.template_summary_resource import TemplateSummaryResource
from components.templates.application.providers.template_registry_provider import (
    get_template_registry,
)
from components.templates.domain.errors import UnknownTemplateKind

logger = logging.getLogger(__name__)


class TemplateGalleryView(APIView):
    """GET /templates/?workspace_id=<uuid>&kind=<kind_id>

    Lists system (global) templates + the workspace's own templates, for one
    kind or (omit ``kind``) across every registered kind. Grouped client-side by
    ``scope`` (system vs workspace) for the gallery.
    """

    # HasWorkspaceMembership reads ?workspace_id= and 403s a non-member, closing
    # the IDOR where any authed user could enumerate another workspace's
    # templates. Omitting workspace_id is allowed → system templates only.
    permission_classes = (IsAuthenticated, HasWorkspaceMembership)

    def get(self, request):
        query = TemplateGalleryRequest.from_query_params(request.query_params)

        registry = get_template_registry()
        try:
            summaries = registry.list_templates(workspace_id=query.workspace_id, kind=query.kind)
        except UnknownTemplateKind as exc:
            return Response(
                {"detail": str(exc), "available_kinds": registry.kinds()},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = [asdict(TemplateSummaryResource.from_summary(s)) for s in summaries]
        return Response(
            {"count": len(results), "kinds": registry.kinds(), "results": results},
            status=status.HTTP_200_OK,
        )
