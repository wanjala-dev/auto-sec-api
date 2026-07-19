"""Integration tests for the full recycle bin lifecycle.

Tests the repository against a real database (SQLite via pytest-django).
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy
from components.recycle_bin.infrastructure.repositories.recycle_bin_repository import DjangoRecycleBinRepository


def _make_entry(
    workspace_id,
    *,
    deleted_by,
    stage=DeletionStage.TRASHED,
    entity_type="budget",
    trashed_until_offset_days=30,
):
    now = datetime.now(timezone.utc)
    return RecycleBinEntry(
        id=uuid4(),
        workspace_id=workspace_id,
        entity_type=entity_type,
        entity_id=uuid4(),
        entity_name="Test Budget",
        stage=stage,
        # FK -> users_customuser.id: must be a persisted user, otherwise the
        # SQLite FK-constraint check at teardown raises IntegrityError.
        deleted_by=deleted_by,
        deleted_at=now,
        trashed_until=now + timedelta(days=trashed_until_offset_days),
        tombstoned_at=now if stage == DeletionStage.TOMBSTONED else None,
        tombstoned_by=deleted_by if stage == DeletionStage.TOMBSTONED else None,
        tombstoned_until=(now + timedelta(days=30)) if stage == DeletionStage.TOMBSTONED else None,
        snapshot={"name": "Test Budget", "amount": "5000"},
        cascade_snapshot={},
        restored_at=None,
        restored_by=None,
    )


@pytest.mark.django_db
class TestDjangoRecycleBinRepository:
    def setup_method(self):
        from infrastructure.persistence.users.models import CustomUser
        from infrastructure.persistence.workspaces.models import Workspace

        self.repo = DjangoRecycleBinRepository()
        # RecycleBinEntry has FKs to users_customuser (deleted_by/tombstoned_by/
        # restored_by) and workspaces.Workspace. The test DB enforces these at
        # teardown, so the actor and workspace must be real persisted rows.
        self.user = CustomUser.objects.create_user(
            username="rb-test-user",
            email="rb-test-user@example.com",
            password="pw",
        )
        self.deleted_by = self.user.id
        self.workspace = Workspace.objects.create(
            workspace_name="RB Test Workspace",
            workspace_owner=self.user,
            status="active",
        )
        self.workspace_id = self.workspace.id
        self.other_workspace = Workspace.objects.create(
            workspace_name="RB Other Workspace",
            workspace_owner=self.user,
            status="active",
        )

    def test_save_and_find_by_id(self):
        entry = _make_entry(self.workspace_id, deleted_by=self.deleted_by)
        self.repo.save(entry)

        found = self.repo.find_by_id(entry.id)
        assert found is not None
        assert found.id == entry.id
        assert found.entity_type == "budget"
        assert found.stage == DeletionStage.TRASHED

    def test_find_by_entity(self):
        entry = _make_entry(self.workspace_id, deleted_by=self.deleted_by)
        self.repo.save(entry)

        found = self.repo.find_by_entity("budget", entry.entity_id)
        assert found is not None
        # entity_id is now persisted as a CharField (polymorphic PK support),
        # so the repository maps it back to a string, not the original UUID.
        assert found.entity_id == str(entry.entity_id)

    def test_find_by_entity_returns_none_when_missing(self):
        assert self.repo.find_by_entity("budget", uuid4()) is None

    def test_list_for_workspace(self):
        for _ in range(3):
            self.repo.save(_make_entry(self.workspace_id, deleted_by=self.deleted_by))
        # Different workspace
        self.repo.save(_make_entry(self.other_workspace.id, deleted_by=self.deleted_by))

        results = self.repo.list_for_workspace(self.workspace_id)
        assert len(results) == 3

    def test_list_for_workspace_filters_by_stage(self):
        self.repo.save(_make_entry(self.workspace_id, deleted_by=self.deleted_by, stage=DeletionStage.TRASHED))
        self.repo.save(_make_entry(self.workspace_id, deleted_by=self.deleted_by, stage=DeletionStage.TOMBSTONED))

        trashed = self.repo.list_for_workspace(self.workspace_id, stage=DeletionStage.TRASHED)
        assert len(trashed) == 1
        assert trashed[0].stage == DeletionStage.TRASHED

    def test_list_for_workspace_filters_by_entity_type(self):
        self.repo.save(_make_entry(self.workspace_id, deleted_by=self.deleted_by, entity_type="budget"))
        self.repo.save(_make_entry(self.workspace_id, deleted_by=self.deleted_by, entity_type="transaction"))

        budgets = self.repo.list_for_workspace(self.workspace_id, entity_type="budget")
        assert len(budgets) == 1
        assert budgets[0].entity_type == "budget"

    def test_count_for_workspace(self):
        for _ in range(5):
            self.repo.save(_make_entry(self.workspace_id, deleted_by=self.deleted_by))

        assert self.repo.count_for_workspace(self.workspace_id) == 5

    def test_delete_entry(self):
        entry = _make_entry(self.workspace_id, deleted_by=self.deleted_by)
        self.repo.save(entry)

        self.repo.delete(entry.id)
        assert self.repo.find_by_id(entry.id) is None

    def test_save_updates_existing_entry(self):
        """Test that saving an entry with the same entity_type + entity_id updates it."""
        entry = _make_entry(self.workspace_id, deleted_by=self.deleted_by)
        self.repo.save(entry)

        import dataclasses
        updated = dataclasses.replace(entry, stage=DeletionStage.TOMBSTONED)
        self.repo.save(updated)

        found = self.repo.find_by_id(entry.id)
        assert found is not None
        assert found.stage == DeletionStage.TOMBSTONED

    def test_find_expired_trashed(self):
        now = datetime.now(timezone.utc)
        # Expired entry (trashed_until in the past)
        expired = _make_entry(self.workspace_id, deleted_by=self.deleted_by, trashed_until_offset_days=-1)
        self.repo.save(expired)

        # Not expired
        fresh = _make_entry(self.workspace_id, deleted_by=self.deleted_by, trashed_until_offset_days=30)
        self.repo.save(fresh)

        results = self.repo.find_expired_trashed(now)
        assert len(results) == 1
        assert results[0].id == expired.id

    def test_find_expired_tombstoned(self):
        now = datetime.now(timezone.utc)
        # Create a tombstoned entry with expired tombstoned_until
        entry = RecycleBinEntry(
            id=uuid4(),
            workspace_id=self.workspace_id,
            entity_type="budget",
            entity_id=uuid4(),
            entity_name="Old Budget",
            stage=DeletionStage.TOMBSTONED,
            deleted_by=self.deleted_by,
            deleted_at=now - timedelta(days=60),
            trashed_until=now - timedelta(days=30),
            tombstoned_at=now - timedelta(days=31),
            tombstoned_by=self.deleted_by,
            tombstoned_until=now - timedelta(days=1),  # Expired
            snapshot={"name": "Old Budget"},
            cascade_snapshot={},
            restored_at=None,
            restored_by=None,
        )
        self.repo.save(entry)

        results = self.repo.find_expired_tombstoned(now)
        assert len(results) == 1
        assert results[0].id == entry.id

    def test_snapshot_preserved(self):
        snapshot = {
            "name": "Q4 Budget",
            "amount": "15000.00",
            "currency": "CAD",
            "line_items": [{"category": "marketing", "amount": "5000"}],
        }
        entry = _make_entry(self.workspace_id, deleted_by=self.deleted_by)
        import dataclasses
        entry = dataclasses.replace(entry, snapshot=snapshot)
        self.repo.save(entry)

        found = self.repo.find_by_id(entry.id)
        assert found.snapshot == snapshot
        assert found.snapshot["line_items"][0]["category"] == "marketing"
