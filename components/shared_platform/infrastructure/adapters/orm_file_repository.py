"""ORM adapter implementing FileRepositoryPort."""

from __future__ import annotations

from uuid import UUID

from components.shared_platform.domain.entities.file_entity import FileEntity
from components.shared_platform.application.ports.file_repository_port import FileRepositoryPort


def _to_entity(obj) -> FileEntity:
    return FileEntity(
        id=obj.id,
        owner_id=UUID(str(obj.owner_id)),
        workspace_id=obj.workspace_id,
        file_path=str(obj.file),
        file_type=obj.file_type,
        processing_status=obj.processing_status,
        processing_error=obj.processing_error,
        processed_at=obj.processed_at,
        created=obj.created,
    )


class OrmFileRepository(FileRepositoryPort):

    def create(
        self,
        *,
        owner_id: UUID,
        workspace_id: str,
        file_obj,
        file_type: str,
    ) -> FileEntity:
        from infrastructure.persistence.uploads.models import File

        instance = File.objects.create(
            owner_id=owner_id,
            workspace_id=workspace_id,
            file=file_obj,
            file_type=file_type,
        )
        return _to_entity(instance)

    def create_for_external_upload(
        self,
        *,
        owner_id: UUID,
        workspace_id: str,
        storage_key: str,
        file_type: str,
    ) -> FileEntity:
        from infrastructure.persistence.uploads.models import File

        # Django ``FileField`` accepts ``name=<storage-relative path>``
        # without bytes attached. The frontend PUTs the bytes directly
        # to S3 using a presigned URL whose key matches this name, so
        # ``file.url`` re-signs against the live object on every read.
        instance = File.objects.create(
            owner_id=owner_id,
            workspace_id=workspace_id,
            file=storage_key,
            file_type=file_type,
        )
        return _to_entity(instance)

    def find_by_id(self, file_id: int) -> FileEntity | None:
        from infrastructure.persistence.uploads.models import File

        try:
            obj = File.objects.get(id=file_id)
            return _to_entity(obj)
        except File.DoesNotExist:
            return None

    def update_processing_status(self, file_id: int, status: str) -> None:
        from infrastructure.persistence.uploads.models import File

        File.objects.filter(id=file_id).update(processing_status=status)

    def mark_index_requested(self, file_id: int, *, now) -> None:
        from infrastructure.persistence.uploads.models import File

        File.objects.filter(id=file_id).update(
            processing_status="pending",
            index_requested_at=now,
            processing_error=None,
        )

    def count_index_requests_since(self, workspace_id: str, *, since) -> int:
        from infrastructure.persistence.uploads.models import File

        return File.objects.filter(
            workspace_id=workspace_id,
            index_requested_at__gte=since,
        ).count()

    def recent_index_outcomes(self, workspace_id: str, *, limit: int, requested_after) -> list[str]:
        from infrastructure.persistence.uploads.models import File

        return list(
            File.objects.filter(
                workspace_id=workspace_id,
                index_requested_at__gte=requested_after,
                processing_status__in=("completed", "failed"),
            )
            .order_by("-index_requested_at")
            .values_list("processing_status", flat=True)[:limit]
        )

    def get_absolute_file_url(self, file_id: int, *, request=None) -> str | None:
        from infrastructure.persistence.uploads.models import File

        try:
            obj = File.objects.get(id=file_id)
            return obj.get_absolute_file_url(request=request)
        except File.DoesNotExist:
            return None
