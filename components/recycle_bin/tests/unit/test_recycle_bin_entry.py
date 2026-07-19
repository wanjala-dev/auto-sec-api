"""Unit tests for the RecycleBinEntry domain entity."""

from datetime import datetime, timezone
from uuid import uuid4

from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry
from components.recycle_bin.domain.enums import DeletionStage


class TestRecycleBinEntry:
    def test_create_trashed_entry(self):
        now = datetime.now(timezone.utc)
        entry = RecycleBinEntry(
            id=uuid4(),
            workspace_id=uuid4(),
            entity_type="budget",
            entity_id=uuid4(),
            entity_name="Q4 Marketing Budget",
            stage=DeletionStage.TRASHED,
            deleted_by=uuid4(),
            deleted_at=now,
            trashed_until=now,
            tombstoned_at=None,
            tombstoned_by=None,
            tombstoned_until=None,
            snapshot={"name": "Q4 Marketing Budget", "amount": "15000"},
            cascade_snapshot={},
            restored_at=None,
            restored_by=None,
        )
        assert entry.stage == DeletionStage.TRASHED
        assert entry.entity_type == "budget"
        assert entry.tombstoned_at is None
        assert entry.restored_at is None

    def test_entry_is_frozen(self):
        now = datetime.now(timezone.utc)
        entry = RecycleBinEntry(
            id=uuid4(),
            workspace_id=uuid4(),
            entity_type="budget",
            entity_id=uuid4(),
            entity_name="Test",
            stage=DeletionStage.TRASHED,
            deleted_by=None,
            deleted_at=now,
            trashed_until=now,
            tombstoned_at=None,
            tombstoned_by=None,
            tombstoned_until=None,
            snapshot={},
            cascade_snapshot={},
            restored_at=None,
            restored_by=None,
        )
        try:
            entry.stage = DeletionStage.TOMBSTONED  # type: ignore
            assert False, "Should not be able to mutate frozen dataclass"
        except AttributeError:
            pass


class TestDeletionStage:
    def test_stage_values(self):
        assert DeletionStage.TRASHED == "trashed"
        assert DeletionStage.TOMBSTONED == "tombstoned"

    def test_stage_is_str(self):
        assert isinstance(DeletionStage.TRASHED, str)
