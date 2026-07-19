"""Audit log API controller — read-only history for tracked entities."""

from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.audit.mappers.rest.audit_serializers import (
    EntityAuditLogSerializer,
)
from components.audit.application.providers.audit_models_provider import get_audit_models_provider

EntityAuditLog = get_audit_models_provider().EntityAuditLog


class AuditLogListView(APIView):
    """GET /audit/entries/?entity_type=campaign.campaign&object_id=<uuid>&field_name=goal_amount

    Returns paginated audit history for a specific entity, optionally
    narrowed to a single field. Workspace members may read.
    """

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        entity_type = request.query_params.get("entity_type", "")
        object_id = request.query_params.get("object_id", "")
        field_name = request.query_params.get("field_name")
        limit = min(int(request.query_params.get("limit", "50")), 200)

        if not entity_type or not object_id:
            return Response(
                {"error": "entity_type and object_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        app_label, _, model_name = entity_type.partition(".")
        if not model_name:
            ct = ContentType.objects.filter(model=entity_type).first()
        else:
            ct = ContentType.objects.filter(
                app_label=app_label, model=model_name
            ).first()

        if ct is None:
            return Response([], status=status.HTTP_200_OK)

        qs = (
            EntityAuditLog.objects.filter(
                content_type=ct, object_id=str(object_id)
            )
            .select_related("actor", "content_type")
            .order_by("-created_at")
        )
        if field_name:
            qs = qs.filter(field_name=field_name)
        qs = qs[:limit]

        serializer = EntityAuditLogSerializer(qs, many=True)
        return Response(serializer.data)
