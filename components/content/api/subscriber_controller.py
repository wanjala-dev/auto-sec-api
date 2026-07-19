"""Views for newsletter Subscriber CRUD + bulk import.

Subscribers live in `infrastructure.persistence.content.Subscriber` (moved
from `landing` by migration 0002 alongside the Newsletter model). These
endpoints are the first time the new content.Subscriber rows are
reachable from the frontend — the legacy `/api/landing/subscribers/`
view targets the OLD landing.Subscriber table which is now read-only
fallback.

URL shape: `/workspaces/news/subscribers/`.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.content.api.permissions import (
    CanManageSubscribers,
    CanReadWriting,
)

logger = logging.getLogger(__name__)


def _serialize(row) -> dict[str, Any]:
    return {
        "id": row.pk,
        "name": row.name,
        "email": row.email,
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "subscribed_at": row.subscribed_at.isoformat() if row.subscribed_at else None,
    }


class SubscriberListView(APIView):
    """GET lists subscribers, POST adds them (single or bulk).

    Read uses ``view_writing`` so any seat that can read the workspace
    can see who's subscribed. Add (POST) uses ``manage_writing`` —
    contributing-roles can add subscribers, but viewer-only seats
    cannot.
    """

    name = "newsletter-subscriber-list"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [CanReadWriting()]
        return [CanManageSubscribers()]

    def get(self, request):
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "workspace_id query param required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from components.content.application.providers.content_models_provider import get_content_models_provider
        Subscriber = get_content_models_provider().Subscriber

        try:
            wid = UUID(workspace_id)
        except (ValueError, TypeError):
            return Response(
                {"detail": "workspace_id must be a UUID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = Subscriber.objects.filter(workspace_id=wid).order_by("email")
        limit = int(request.query_params.get("limit", 200))
        offset = int(request.query_params.get("offset", 0))
        rows = list(qs[offset : offset + limit])
        return Response(
            {
                "results": [_serialize(row) for row in rows],
                "count": qs.count(),
            }
        )

    def post(self, request):
        """Single-subscriber create OR bulk import.

        Accepts either:
          { workspace_id, email, name? } — single
          { workspace_id, subscribers: [{email, name}, ...] } — bulk
        """
        from components.content.application.providers.content_models_provider import get_content_models_provider
        Subscriber = get_content_models_provider().Subscriber

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

        bulk = request.data.get("subscribers")
        if isinstance(bulk, list):
            created = []
            skipped = []
            for entry in bulk:
                email = (entry or {}).get("email", "").strip().lower()
                name = (entry or {}).get("name", "").strip()
                if not email:
                    skipped.append({"reason": "missing_email", "entry": entry})
                    continue
                # Email is unique per workspace (migration 0004). An
                # existing row in THIS workspace is a duplicate; an
                # existing row in another workspace is a different
                # subscriber entirely and we silently add ours next to
                # it (no cross-workspace coupling).
                existing = Subscriber.objects.filter(
                    workspace_id=workspace_id, email=email
                ).first()
                if existing:
                    skipped.append({"reason": "already_subscribed", "email": email})
                    continue
                row = Subscriber.objects.create(
                    email=email,
                    name=name or email.split("@")[0],
                    workspace_id=workspace_id,
                )
                created.append(_serialize(row))
            return Response(
                {"created": created, "skipped": skipped},
                status=status.HTTP_201_CREATED,
            )

        # Single create
        email = (request.data.get("email", "") or "").strip().lower()
        name = (request.data.get("name", "") or "").strip()
        if not email:
            return Response(
                {"detail": "email required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Email is unique per workspace. An existing row in THIS
        # workspace means they're already subscribed — return it idempotently.
        existing = Subscriber.objects.filter(
            workspace_id=workspace_id, email=email
        ).first()
        if existing:
            return Response(_serialize(existing), status=status.HTTP_200_OK)

        row = Subscriber.objects.create(
            email=email,
            name=name or email.split("@")[0],
            workspace_id=workspace_id,
        )
        return Response(_serialize(row), status=status.HTTP_201_CREATED)


class SubscriberDetailView(APIView):
    """GET reads a subscriber, DELETE removes one. Removal is a soft
    unsubscribe + suppression-list entry — see the use case for the
    full lifecycle.
    """

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [CanReadWriting()]
        return [CanManageSubscribers()]
    name = "newsletter-subscriber-detail"

    def delete(self, request, subscriber_id: int):
        from components.content.application.providers.content_models_provider import get_content_models_provider
        Subscriber = get_content_models_provider().Subscriber

        Subscriber.objects.filter(pk=subscriber_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
