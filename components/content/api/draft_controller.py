"""Views for WritingDraft CRUD + publish action + PDF export."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.content.api.permissions import (
    CanComposeWriting,
    CanReadWriting,
)
from components.content.application.providers.writing_provider import WritingProvider
from components.content.domain.errors import (
    ContentValidationError,
    WritingDraftInvalidTransitionError,
    WritingDraftNotFoundError,
)

logger = logging.getLogger(__name__)


def _serialize(entity) -> dict[str, Any]:
    related_id = getattr(entity, "related_entity_id", None)
    return {
        "id": str(entity.id),
        "workspace_id": str(entity.workspace_id),
        "title": entity.title,
        "body_html": entity.body_html,
        "kind": entity.kind,
        "status": entity.status,
        "author_id": entity.author_id,
        "template_id": str(entity.template_id) if entity.template_id else None,
        "ai_drafted": entity.ai_drafted,
        "related_entity_type": getattr(entity, "related_entity_type", "") or "",
        "related_entity_id": str(related_id) if related_id else None,
        "pdf_key": entity.pdf_key,
        # Design-template drafts carry a block-tree layout here (task #19);
        # the FE renders it as the designed document when present.
        "metadata": dict(entity.metadata or {}),
        "created_at": entity.created_at.isoformat(),
        "updated_at": entity.updated_at.isoformat(),
    }


class WritingDraftListView(APIView):
    """GET lists drafts, POST creates one."""

    name = "writing-draft-list"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [CanReadWriting()]
        return [CanComposeWriting()]

    def get(self, request):
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "workspace_id query param required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from components.content.application.providers.writing_draft_repository_provider import (
            get_writing_draft_repository_provider,
        )

        items = (
            get_writing_draft_repository_provider()
            .repository()
            .list_for_workspace(
                workspace_id=UUID(workspace_id),
                kind=request.query_params.get("kind"),
                status=request.query_params.get("status"),
                limit=int(request.query_params.get("limit", 100)),
                offset=int(request.query_params.get("offset", 0)),
            )
        )
        return Response({"results": [_serialize(i) for i in items]})

    def post(self, request):
        workspace_id = request.data.get("workspace_id")
        title = request.data.get("title")
        kind = request.data.get("kind")
        if not all([workspace_id, title, kind]):
            return Response(
                {"detail": "workspace_id, title, kind required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        template_id_raw = request.data.get("template_id")
        template_id = UUID(template_id_raw) if template_id_raw else None

        # Optional entity-scoped link. Required by the use case for
        # kind in {recipient_update, project_update, event_update,
        # campaign_update}; ignored for free-form kinds. The use case
        # raises ValueError on mismatch and the catch below maps to a
        # 400 response.
        related_entity_type = request.data.get("related_entity_type", "")
        related_entity_id_raw = request.data.get("related_entity_id")
        related_entity_id = UUID(related_entity_id_raw) if related_entity_id_raw else None

        use_case = WritingProvider().build_create_writing_draft()
        try:
            entity = use_case.execute(
                workspace_id=UUID(workspace_id),
                author_id=request.user.id,
                title=title,
                kind=kind,
                body_html=request.data.get("body_html", ""),
                template_id=template_id,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
                metadata=request.data.get("metadata", {}),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize(entity), status=status.HTTP_201_CREATED)


class WritingDraftDetailView(APIView):
    """GET reads, PATCH edits, DELETE archives."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [CanReadWriting()]
        return [CanComposeWriting()]

    name = "writing-draft-detail"

    def get(self, request, draft_id: UUID):
        from components.content.application.providers.writing_draft_repository_provider import (
            get_writing_draft_repository_provider,
        )

        entity = get_writing_draft_repository_provider().repository().get(draft_id=draft_id)
        if entity is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(entity))

    def patch(self, request, draft_id: UUID):
        from components.content.application.providers.writing_draft_repository_provider import (
            get_writing_draft_repository_provider,
        )

        try:
            # PARTIAL update: absent fields stay untouched (None is not "").
            # The old `.get("title", "")` default silently wiped the title
            # on any body-only PATCH — and then 500'd (2026-07-12).
            entity = (
                get_writing_draft_repository_provider()
                .repository()
                .update_body(
                    draft_id=draft_id,
                    title=request.data.get("title"),
                    body_html=request.data.get("body_html"),
                    metadata=request.data.get("metadata"),
                )
            )
        except WritingDraftNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except ContentValidationError as exc:
            # Domain validation (blank title etc.) is a client error, not a 500.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize(entity))

    def delete(self, request, draft_id: UUID):
        """Deleting a draft ALWAYS goes through the recycle bin (task #29
        — Henry: never hard-delete an artifact): the row is flag-hidden
        from every read path and restorable from the bin. Idempotent —
        an already-trashed draft returns 204."""
        from components.content.application.providers.writing_draft_repository_provider import (
            get_writing_draft_repository_provider,
        )
        from components.recycle_bin.application.commands.trash_command import (
            TrashCommand,
        )
        from components.recycle_bin.application.providers.recycle_bin_provider import (
            get_recycle_bin_service,
        )
        from components.shared_kernel.domain.errors import ConflictError

        draft = get_writing_draft_repository_provider().repository().get(draft_id=draft_id)
        if draft is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            get_recycle_bin_service().trash(
                TrashCommand(
                    workspace_id=draft.workspace_id,
                    entity_type="writing_draft",
                    entity_id=str(draft_id),
                    deleted_by=request.user.id,
                )
            )
        except ConflictError:
            # Already in the bin (race with a concurrent delete) — the
            # outcome the caller asked for already holds.
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class WritingDraftPublishView(APIView):
    """Publishing a draft is a compose-level action — same gate as edit."""

    permission_classes = (CanComposeWriting,)
    name = "writing-draft-publish"

    def post(self, request, draft_id: UUID):
        use_case = WritingProvider().build_publish_writing_draft()
        try:
            entity = use_case.execute(
                draft_id=draft_id,
                actor_id=request.user.id,
                now=timezone.now(),
            )
        except WritingDraftNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except WritingDraftInvalidTransitionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(_serialize(entity))


class WritingDraftSendEmailView(APIView):
    """POST /content/drafts/<id>/send-email/ — email the draft to contacts.

    The distribution leg of the share flow (task #20): 1:few correspondence
    to explicit contacts, capped in the use case — bulk goes through the
    newsletter surface. Sending externally is a compose-level action.
    Body: ``{contact_ids: [...], note?: str}``.
    """

    permission_classes = (CanComposeWriting,)
    name = "writing-draft-send-email"

    def post(self, request, draft_id: UUID):
        raw_ids = request.data.get("contact_ids") or []
        contact_ids = []
        if isinstance(raw_ids, list):
            for value in raw_ids[:50]:
                try:
                    contact_ids.append(UUID(str(value)))
                except (TypeError, ValueError):
                    continue
        try:
            # The draft row is the workspace authority — the use case
            # derives it server-side; no client-supplied workspace_id.
            result = (
                WritingProvider()
                .build_send_draft_email()
                .execute(
                    draft_id=draft_id,
                    contact_ids=contact_ids,
                    note=str(request.data.get("note") or "")[:2000],
                )
            )
        except ContentValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


class WritingDraftExportPdfView(APIView):
    """PDF export is a read-shaped action — anyone who can read can export."""

    permission_classes = (CanReadWriting,)
    name = "writing-draft-export-pdf"

    def post(self, request, draft_id: UUID):
        from components.content.workers.tasks import render_writing_draft_pdf

        async_result = render_writing_draft_pdf.delay(str(draft_id))
        return Response(
            {"task_id": async_result.id, "status": "pending"},
            status=status.HTTP_202_ACCEPTED,
        )
