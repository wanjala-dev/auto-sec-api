"""Recycle Bin REST controller.

Thin primary adapter -- parses requests, calls the application service,
and returns serialized responses. No business logic.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from uuid import UUID

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from components.recycle_bin.api.resources.recycle_bin_resource import RecycleBinEntryResource
from components.recycle_bin.application.commands.restore_command import RestoreCommand
from components.recycle_bin.application.commands.trash_command import TrashCommand
from components.recycle_bin.application.providers.recycle_bin_provider import get_recycle_bin_service
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.errors import (
    EntityAlreadyTrashedError,
    EntryNotFoundError,
    EntryNotRestorableError,
)
from components.recycle_bin.mappers.rest.recycle_bin_serializers import RecycleBinEntrySerializer

logger = logging.getLogger(__name__)


def _entry_to_resource(entry) -> dict:
    """Convert a domain entity to a serializable resource dict."""
    resource = RecycleBinEntryResource(
        id=entry.id,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        entity_name=entry.entity_name,
        stage=entry.stage.value if hasattr(entry.stage, "value") else str(entry.stage),
        deleted_by=entry.deleted_by,
        deleted_at=entry.deleted_at,
        trashed_until=entry.trashed_until,
        tombstoned_at=entry.tombstoned_at,
        snapshot=entry.snapshot,
    )
    return asdict(resource)


# ── Views ────────────────────────────────────────────────────────────


class RecycleBinListView(APIView):
    """GET /recycle-bin/ -- list bin entries for a workspace."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        service = get_recycle_bin_service()
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "workspace_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            workspace_id = UUID(workspace_id)
        except (ValueError, TypeError):
            return Response(
                {"detail": "Invalid workspace_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        entity_type = request.query_params.get("type")
        stage_str = request.query_params.get("stage")
        stage = DeletionStage(stage_str) if stage_str else None

        limit = int(request.query_params.get("limit", 50))
        offset = int(request.query_params.get("offset", 0))

        entries = service.list_bin(
            workspace_id=workspace_id,
            stage=stage,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
        )
        total = service.count_bin(workspace_id=workspace_id, stage=stage)

        data = [_entry_to_resource(e) for e in entries]
        serializer = RecycleBinEntrySerializer(data, many=True)

        return Response(
            {
                "count": total,
                "limit": limit,
                "offset": offset,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class RecycleBinRestoreView(APIView):
    """POST /recycle-bin/{entry_id}/restore/ -- restore one entry."""

    permission_classes = (IsAuthenticated,)

    def post(self, request, entry_id: UUID):
        service = get_recycle_bin_service()
        command = RestoreCommand(entry_id=entry_id, restored_by=request.user.id, reason=str(request.data.get("reason") or ""))

        try:
            entry = service.restore(command)
        except EntryNotFoundError:
            return Response({"detail": "Entry not found."}, status=status.HTTP_404_NOT_FOUND)
        except EntryNotRestorableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        data = _entry_to_resource(entry)
        serializer = RecycleBinEntrySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RecycleBinDeleteOneView(APIView):
    """DELETE /recycle-bin/{entry_id}/ -- permanently delete one item."""

    permission_classes = (IsAuthenticated,)

    def delete(self, request, entry_id: UUID):
        service = get_recycle_bin_service()

        try:
            service.permanently_delete_one(entry_id=entry_id, deleted_by=request.user.id, reason=str(request.data.get("reason") or ""))
        except EntryNotFoundError:
            return Response({"detail": "Entry not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(status=status.HTTP_204_NO_CONTENT)


class RecycleBinEmptyView(APIView):
    """DELETE /recycle-bin/empty/ -- empty entire bin for a workspace."""

    permission_classes = (IsAuthenticated,)

    def delete(self, request):
        service = get_recycle_bin_service()
        workspace_id = request.query_params.get("workspace_id")
        if not workspace_id:
            return Response(
                {"detail": "workspace_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            workspace_id = UUID(workspace_id)
        except (ValueError, TypeError):
            return Response(
                {"detail": "Invalid workspace_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        count = service.empty_bin(workspace_id=workspace_id, emptied_by=request.user.id, reason=str(request.data.get("reason") or ""))
        return Response({"count": count}, status=status.HTTP_200_OK)


class RecycleBinTrashView(APIView):
    """POST /recycle-bin/trash/ -- soft-delete one entity into the bin.

    Body: {"workspace_id": "<uuid>", "entity_type": "transaction|budget|category", "entity_id": "<uuid>"}

    Soft-deletes the underlying row via the adapter registered for the
    entity type and creates a RecycleBinEntry that holds the snapshot.
    Returns the entry so the client can show Undo / link to /recycle-bin/.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        workspace_id_raw = request.data.get("workspace_id")
        entity_type = request.data.get("entity_type")
        entity_id_raw = request.data.get("entity_id")

        if not workspace_id_raw or not entity_type or not entity_id_raw:
            return Response(
                {"detail": "workspace_id, entity_type, and entity_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            workspace_id = UUID(str(workspace_id_raw))
        except (ValueError, TypeError):
            return Response(
                {"detail": "workspace_id must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # entity_id is the trashed row's PK. Transaction / Budget /
        # Category use BigAutoField; future entity types may use UUID.
        # The bin stores it as a string and adapters convert when they
        # touch the ORM. Accept any non-empty string.
        entity_id = str(entity_id_raw).strip()
        if not entity_id:
            return Response(
                {"detail": "entity_id must be a non-empty string."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = get_recycle_bin_service()
        if entity_type not in service.provider.supported_types():
            return Response(
                {
                    "detail": (
                        f"Entity type '{entity_type}' is not trashable. "
                        f"Supported: {service.provider.supported_types()}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = TrashCommand(
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            deleted_by=request.user.id,
            reason=str(request.data.get("reason") or ""),
        )

        try:
            entry = service.trash(command)
        except EntityAlreadyTrashedError:
            return Response(
                {"detail": "Entity is already in the recycle bin."},
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        data = _entry_to_resource(entry)
        serializer = RecycleBinEntrySerializer(data)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RecycleBinTrashBulkView(APIView):
    """POST /recycle-bin/trash/bulk/ -- soft-delete many entities at once.

    Body: {"workspace_id": "<uuid>", "entity_type": "...", "entity_ids": ["<uuid>", ...]}

    Same per-row semantics as RecycleBinTrashView. Per-row failures are
    captured and reported in the response so a partial bulk delete is
    visible to the client.

    Cap: 500 ids per request. Themis runs unbounded bulk-trash through a
    background job (Sidekiq); we don't have an async path for this yet,
    so we cap synchronously and let the client chunk. Raising the cap
    requires moving this off the request path into a Celery task that
    publishes a completion event.
    """

    MAX_BULK_IDS = 500

    permission_classes = (IsAuthenticated,)

    def post(self, request):
        workspace_id_raw = request.data.get("workspace_id")
        entity_type = request.data.get("entity_type")
        entity_ids_raw = request.data.get("entity_ids") or []

        if not workspace_id_raw or not entity_type or not isinstance(entity_ids_raw, list):
            return Response(
                {"detail": "workspace_id, entity_type, and entity_ids[] are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(entity_ids_raw) > self.MAX_BULK_IDS:
            return Response(
                {
                    "detail": (
                        f"Cannot bulk-trash more than {self.MAX_BULK_IDS} entities in a single request. "
                        f"Got {len(entity_ids_raw)}. Chunk the list and retry."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            workspace_id = UUID(str(workspace_id_raw))
        except (ValueError, TypeError):
            return Response(
                {"detail": "workspace_id must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = get_recycle_bin_service()
        if entity_type not in service.provider.supported_types():
            return Response(
                {
                    "detail": (
                        f"Entity type '{entity_type}' is not trashable. "
                        f"Supported: {service.provider.supported_types()}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        bulk_reason = str(request.data.get("reason") or "")
        trashed: list[dict] = []
        failed: list[dict] = []
        for raw_id in entity_ids_raw:
            entity_id = str(raw_id).strip() if raw_id is not None else ""
            if not entity_id:
                failed.append({"entity_id": str(raw_id), "reason": "empty entity_id"})
                continue

            command = TrashCommand(
                workspace_id=workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                deleted_by=request.user.id,
                reason=bulk_reason,
            )
            try:
                entry = service.trash(command)
                trashed.append(_entry_to_resource(entry))
            except EntityAlreadyTrashedError:
                failed.append({"entity_id": str(entity_id), "reason": "already trashed"})
            except Exception as exc:
                logger.exception(
                    "recycle_bin_bulk_trash_failed entity_type=%s entity_id=%s",
                    entity_type, entity_id,
                )
                failed.append({"entity_id": str(entity_id), "reason": str(exc)[:200]})

        serializer = RecycleBinEntrySerializer(trashed, many=True)
        return Response(
            {"trashed": serializer.data, "failed": failed},
            status=status.HTTP_207_MULTI_STATUS if failed else status.HTTP_201_CREATED,
        )
