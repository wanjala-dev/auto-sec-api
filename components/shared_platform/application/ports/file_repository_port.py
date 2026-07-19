"""Port for file persistence and processing operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.shared_platform.domain.entities.file_entity import FileEntity


class FileRepositoryPort(ABC):
    """Secondary/driven port for file upload read/write operations."""

    @abstractmethod
    def create(
        self,
        *,
        owner_id: UUID,
        workspace_id: str,
        file_obj,
        file_type: str,
    ) -> FileEntity:
        ...

    @abstractmethod
    def create_for_external_upload(
        self,
        *,
        owner_id: UUID,
        workspace_id: str,
        storage_key: str,
        file_type: str,
    ) -> FileEntity:
        """Register a File row whose bytes were uploaded out-of-band
        (e.g. via a presigned PUT directly to S3). The row records the
        storage key so downstream FK/M2M references work without the
        bytes ever traversing Django.

        Orphan rows (browser issued a PUT URL but never uploaded) are
        an accepted tradeoff for skipping the confirm-step round-trip;
        a future sweep job can prune rows whose S3 ``HEAD`` 404s.
        """

    @abstractmethod
    def find_by_id(self, file_id: int) -> FileEntity | None:
        ...

    @abstractmethod
    def update_processing_status(
        self, file_id: int, status: str
    ) -> None:
        ...

    @abstractmethod
    def mark_index_requested(self, file_id: int, *, now) -> None:
        """Record an explicit index request: status → pending,
        ``index_requested_at`` stamped, any previous error cleared."""

    @abstractmethod
    def count_index_requests_since(self, workspace_id: str, *, since) -> int:
        """How many index requests the workspace made since ``since`` —
        the accounting read behind the daily quota."""

    @abstractmethod
    def recent_index_outcomes(self, workspace_id: str, *, limit: int, requested_after) -> list[str]:
        """Statuses of the workspace's most recent TERMINAL index attempts
        (completed/failed) requested after ``requested_after``, newest
        first. Feeds the failure circuit-breaker."""

    @abstractmethod
    def get_absolute_file_url(self, file_id: int, *, request=None) -> str | None:
        ...
