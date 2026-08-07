"""Tag vocabulary CRUD API (ADR 0015 D6). Thin, capability-gated, ORM-free.

Gates (D4, tightened for the read-only viewer role): list — any active workspace
member; create — ``manage_findings`` capability (owner/admin/member roles; the
viewer role is read-only and gets 403); rename/recolor/delete/restore — workspace
owner/admin (destructive *vocabulary* operations affect every member's saved views
and filters — the Snyk precedent). System tags (``kind="system"``) are
platform-managed: user writes are rejected in the repository with
``ReservedTagError``.
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from components.membership.api.permissions import has_workspace_permission
from components.tagging.domain.errors import (
    DuplicateTagError,
    InvalidTagError,
    ReservedTagError,
    TagLimitExceededError,
    TagNotFoundError,
)

# Capability gate for vocabulary writes: tags exist to organize findings, so tag
# creation rides the same ``manage_findings`` key as finding tagging (mirrors the
# ``CanManageIntegrations`` pattern in integrations).
CanManageFindingTags = has_workspace_permission("manage_findings")

# Domain error → (API error code, HTTP status). The taxonomy mapping the D6
# contract pins: invalid_tag 400, reserved_tag 400, tag_limit_exceeded 400,
# duplicate_tag 409, not_found 404.
_ERROR_MAP = (
    (TagNotFoundError, "not_found", 404),
    (DuplicateTagError, "duplicate_tag", 409),
    (ReservedTagError, "reserved_tag", 400),
    (TagLimitExceededError, "tag_limit_exceeded", 400),
    (InvalidTagError, "invalid_tag", 400),
)


def _error_response(exc: Exception) -> Response:
    for error_cls, code, status in _ERROR_MAP:
        if isinstance(exc, error_cls):
            return Response({"success": False, "error": code, "detail": str(exc)}, status=status)
    raise exc


class TagListCreateView(APIView):
    """GET (list) + POST (create) /tagging/workspaces/<ws>/tags/.

    GET is member-gated (any active member reads the vocabulary); POST requires the
    ``manage_findings`` capability, so read-only viewers cannot grow the shared
    vocabulary.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "tagging-tags"

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated(), CanManageFindingTags()]
        return super().get_permissions()

    def get(self, request, workspace_id):
        from components.tagging.api.requests.list_tags_request import ListTagsRequest
        from components.tagging.api.resources.tag_resource import TagResource
        from components.tagging.application.providers.tagging_provider import TaggingProvider
        from components.tagging.infrastructure.services.workspace_access import is_workspace_member

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        req = ListTagsRequest.from_request(request, workspace_id)
        items, total = TaggingProvider.build_list_tags_use_case().execute(
            req.workspace_id,
            namespace=req.namespace,
            q=req.q,
            with_usage=req.include_usage,
            limit=req.limit,
            offset=req.offset,
        )
        return Response({"success": True, "data": TagResource.page(items, total)})

    def post(self, request, workspace_id):
        from components.tagging.api.requests.create_tag_request import CreateTagRequest
        from components.tagging.api.resources.tag_resource import TagResource
        from components.tagging.application.providers.tagging_provider import TaggingProvider

        req = CreateTagRequest.from_request(request, workspace_id)
        try:
            tag = TaggingProvider.build_create_tag_use_case().execute(req.to_command())
        except (TagNotFoundError, DuplicateTagError, ReservedTagError, TagLimitExceededError, InvalidTagError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": TagResource.from_entity(tag)}, status=201)


class TagDetailView(APIView):
    """PATCH (rename/recolor/restore) + DELETE (soft delete)
    /tagging/workspaces/<ws>/tags/<tag_id>/ — admin-gated (D4)."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "tagging-tag-detail"

    def patch(self, request, workspace_id, tag_id):
        from components.tagging.api.requests.update_tag_request import UpdateTagRequest
        from components.tagging.api.resources.tag_resource import TagResource
        from components.tagging.application.providers.tagging_provider import TaggingProvider
        from components.tagging.infrastructure.services.workspace_access import is_workspace_admin

        if not is_workspace_admin(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        req = UpdateTagRequest.from_request(request, workspace_id, tag_id)
        try:
            tag = TaggingProvider.build_update_tag_use_case().execute(req.to_command())
        except (TagNotFoundError, DuplicateTagError, ReservedTagError, TagLimitExceededError, InvalidTagError) as exc:
            return _error_response(exc)
        return Response({"success": True, "data": TagResource.from_entity(tag)})

    def delete(self, request, workspace_id, tag_id):
        from components.tagging.application.commands.delete_tag_command import DeleteTagCommand
        from components.tagging.application.providers.tagging_provider import TaggingProvider
        from components.tagging.infrastructure.services.workspace_access import is_workspace_admin

        if not is_workspace_admin(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)

        actor_id = str(getattr(request.user, "id", "") or "") or None
        try:
            TaggingProvider.build_delete_tag_use_case().execute(
                DeleteTagCommand(workspace_id=workspace_id, tag_id=tag_id, actor_id=actor_id)
            )
        except (TagNotFoundError, ReservedTagError) as exc:
            return _error_response(exc)
        return Response({"success": True})
