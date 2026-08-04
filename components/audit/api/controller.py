"""Audit log API controller — read-only history for tracked entities."""

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.audit.api.permissions import IsAuditWorkspaceMember
from components.audit.api.requests.audit_log_list_request import AuditLogListRequest
from components.audit.application.providers.audit_log_provider import get_audit_log_provider
from components.audit.mappers.rest.audit_serializers import AuditEntrySerializer

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


def _parse_dt(raw):
    """Parse an ISO-8601 ``since``/``until`` query param, or return None.

    Tolerant by design: a malformed date narrows nothing rather than
    400ing the whole feed (the caller's other filters still apply).
    """
    if not raw:
        return None
    from django.utils.dateparse import parse_date, parse_datetime

    value = parse_datetime(raw)
    if value is not None:
        return value
    day = parse_date(raw)
    if day is None:
        return None
    from datetime import datetime, time

    from django.utils.timezone import get_current_timezone, make_aware

    return make_aware(datetime.combine(day, time.min), get_current_timezone())


class AuditLogListView(APIView):
    """GET /audit/entries/?workspace_id=<uuid>&entity_type=project.task&object_id=<uuid>&field_name=deletion_stage

    Returns audit history for a specific entity, optionally narrowed to
    a single field. Tenant-gated: the caller must name the workspace
    with ``workspace_id`` and be a member of it
    (``IsAuditWorkspaceMember``), and the returned entries are scoped
    to that workspace by the repository.
    """

    permission_classes = (permissions.IsAuthenticated, IsAuditWorkspaceMember)

    def get(self, request):
        entity_type = request.query_params.get("entity_type", "")
        object_id = request.query_params.get("object_id", "")
        if not entity_type or not object_id:
            return Response(
                {"error": "entity_type and object_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            limit = int(request.query_params.get("limit", _DEFAULT_LIMIT))
        except (TypeError, ValueError):
            return Response(
                {"error": "limit must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, _MAX_LIMIT))

        list_request = AuditLogListRequest(
            workspace_id=request.query_params.get("workspace_id", "").strip(),
            entity_type=entity_type,
            object_id=object_id,
            field_name=request.query_params.get("field_name") or None,
            limit=limit,
        )

        entries = (
            get_audit_log_provider()
            .entity_history_use_case()
            .execute(
                entity_type=list_request.entity_type,
                entity_id=list_request.object_id,
                workspace_id=list_request.workspace_id,
                field_name=list_request.field_name,
                limit=list_request.limit,
            )
        )

        serializer = AuditEntrySerializer(entries, many=True)
        return Response(serializer.data)


class WorkspaceAuditLogListView(APIView):
    """GET /audit/workspace/entries/?workspace_id=<uuid>&entity_type=&field_name=&actor_id=&since=&until=&page=

    The auditor read surface: a workspace-wide "who changed what, when"
    feed, newest first, filterable and paginated. Same tenant gate as
    the per-entity view (``IsAuditWorkspaceMember`` — explicit
    ``workspace_id`` + active membership), and the repository scopes
    every row to that workspace. Read-only: only GET is defined, so no
    role (including the read-only auditor) can mutate through it.
    """

    permission_classes = (permissions.IsAuthenticated, IsAuditWorkspaceMember)

    def get(self, request):
        workspace_id = (request.query_params.get("workspace_id") or "").strip()

        try:
            limit = int(request.query_params.get("limit", _DEFAULT_LIMIT))
            page = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            return Response(
                {"error": "limit and page must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, _MAX_LIMIT))
        page = max(1, page)
        offset = (page - 1) * limit

        since = _parse_dt(request.query_params.get("since"))
        until = _parse_dt(request.query_params.get("until"))

        entries, total = (
            get_audit_log_provider()
            .workspace_history_use_case()
            .execute(
                workspace_id=workspace_id,
                entity_type=(request.query_params.get("entity_type") or "").strip() or None,
                field_name=(request.query_params.get("field_name") or "").strip() or None,
                actor_id=(request.query_params.get("actor_id") or "").strip() or None,
                since=since,
                until=until,
                limit=limit,
                offset=offset,
            )
        )

        serializer = AuditEntrySerializer(entries, many=True)
        return Response(
            {
                "count": total,
                "page": page,
                "limit": limit,
                "results": serializer.data,
            }
        )
