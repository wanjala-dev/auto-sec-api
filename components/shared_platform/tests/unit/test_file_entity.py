"""Unit tests for FileEntity — immutable file domain entity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from components.shared_platform.domain.entities.file_entity import FileEntity


class TestFileEntity:
    """Test suite for FileEntity immutable dataclass."""

    def test_file_entity_creation_with_all_fields(self):
        """Should create FileEntity with all fields populated."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)
        processed_at = datetime(2025, 1, 1, 13, 0, 0)

        entity = FileEntity(
            id=1,
            owner_id=owner_id,
            workspace_id="ws-123",
            file_path="/uploads/document.pdf",
            file_type="pdf",
            processing_status="completed",
            processing_error=None,
            processed_at=processed_at,
            created=now,
        )

        assert entity.id == 1
        assert entity.owner_id == owner_id
        assert entity.workspace_id == "ws-123"
        assert entity.file_path == "/uploads/document.pdf"
        assert entity.file_type == "pdf"
        assert entity.processing_status == "completed"
        assert entity.processing_error is None
        assert entity.processed_at == processed_at
        assert entity.created == now

    def test_file_entity_creation_with_null_optional_fields(self):
        """Should create FileEntity with None for optional fields."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        entity = FileEntity(
            id=2,
            owner_id=owner_id,
            workspace_id=None,
            file_path="/uploads/image.png",
            file_type="image",
            processing_status="pending",
            processing_error=None,
            processed_at=None,
            created=now,
        )

        assert entity.workspace_id is None
        assert entity.processing_error is None
        assert entity.processed_at is None

    def test_file_entity_creation_with_error_message(self):
        """Should store processing error message."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        entity = FileEntity(
            id=3,
            owner_id=owner_id,
            workspace_id="ws-456",
            file_path="/uploads/corrupted.pdf",
            file_type="pdf",
            processing_status="failed",
            processing_error="PDF parsing failed: corrupted header",
            processed_at=now,
            created=now,
        )

        assert entity.processing_status == "failed"
        assert entity.processing_error == "PDF parsing failed: corrupted header"

    def test_file_entity_is_immutable(self):
        """Should raise error when trying to modify entity fields."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        entity = FileEntity(
            id=4,
            owner_id=owner_id,
            workspace_id="ws-789",
            file_path="/uploads/doc.docx",
            file_type="document",
            processing_status="processing",
            processing_error=None,
            processed_at=None,
            created=now,
        )

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(Exception):  # dataclass raises AttributeError
            entity.processing_status = "completed"

        with pytest.raises(Exception):
            entity.processing_error = "Some error"

        with pytest.raises(Exception):
            entity.id = 999

    def test_file_entity_supports_various_file_types(self):
        """Should accept all valid file types."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        file_types = ["image", "pdf", "document", "other"]

        for file_type in file_types:
            entity = FileEntity(
                id=10,
                owner_id=owner_id,
                workspace_id="ws-test",
                file_path=f"/uploads/file.{file_type}",
                file_type=file_type,
                processing_status="completed",
                processing_error=None,
                processed_at=now,
                created=now,
            )
            assert entity.file_type == file_type

    def test_file_entity_supports_various_processing_statuses(self):
        """Should accept all valid processing statuses."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        statuses = ["pending", "processing", "completed", "failed"]

        for status in statuses:
            entity = FileEntity(
                id=20,
                owner_id=owner_id,
                workspace_id="ws-test",
                file_path="/uploads/file.pdf",
                file_type="pdf",
                processing_status=status,
                processing_error=None if status != "failed" else "Error message",
                processed_at=now if status == "completed" else None,
                created=now,
            )
            assert entity.processing_status == status

    def test_file_entity_with_different_id_types(self):
        """Should accept integer IDs."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        entity = FileEntity(
            id=12345,
            owner_id=owner_id,
            workspace_id="ws-large-id",
            file_path="/uploads/file.pdf",
            file_type="pdf",
            processing_status="completed",
            processing_error=None,
            processed_at=now,
            created=now,
        )

        assert entity.id == 12345

    def test_file_entity_owner_id_is_uuid(self):
        """Should store owner_id as UUID."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        entity = FileEntity(
            id=30,
            owner_id=owner_id,
            workspace_id="ws-uuid-test",
            file_path="/uploads/file.pdf",
            file_type="pdf",
            processing_status="completed",
            processing_error=None,
            processed_at=now,
            created=now,
        )

        assert isinstance(entity.owner_id, UUID)
        assert entity.owner_id == owner_id

    def test_file_entity_equality(self):
        """Should compare equality based on all fields."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        entity1 = FileEntity(
            id=40,
            owner_id=owner_id,
            workspace_id="ws-eq",
            file_path="/uploads/file.pdf",
            file_type="pdf",
            processing_status="completed",
            processing_error=None,
            processed_at=now,
            created=now,
        )

        entity2 = FileEntity(
            id=40,
            owner_id=owner_id,
            workspace_id="ws-eq",
            file_path="/uploads/file.pdf",
            file_type="pdf",
            processing_status="completed",
            processing_error=None,
            processed_at=now,
            created=now,
        )

        assert entity1 == entity2

    def test_file_entity_inequality_on_different_id(self):
        """Should be unequal when any field differs."""
        owner_id = uuid4()
        now = datetime(2025, 1, 1, 12, 0, 0)

        entity1 = FileEntity(
            id=50,
            owner_id=owner_id,
            workspace_id="ws-neq",
            file_path="/uploads/file.pdf",
            file_type="pdf",
            processing_status="completed",
            processing_error=None,
            processed_at=now,
            created=now,
        )

        entity2 = FileEntity(
            id=51,  # Different ID
            owner_id=owner_id,
            workspace_id="ws-neq",
            file_path="/uploads/file.pdf",
            file_type="pdf",
            processing_status="completed",
            processing_error=None,
            processed_at=now,
            created=now,
        )

        assert entity1 != entity2
