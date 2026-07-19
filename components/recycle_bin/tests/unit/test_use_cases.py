"""Unit tests for recycle bin use cases.

All ports are mocked — no DB, no Django.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from components.recycle_bin.application.commands.restore_command import RestoreCommand
from components.recycle_bin.application.commands.trash_command import TrashCommand
from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
from components.recycle_bin.application.use_cases.empty_bin_use_case import EmptyBinUseCase
from components.recycle_bin.application.use_cases.purge_expired_use_case import PurgeExpiredUseCase
from components.recycle_bin.application.use_cases.restore_entity_use_case import RestoreEntityUseCase
from components.recycle_bin.application.use_cases.trash_entity_use_case import TrashEntityUseCase
from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.errors import (
    EntityAlreadyTrashedError,
    EntryNotFoundError,
    EntryNotRestorableError,
)
from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy
from components.shared_kernel.domain.errors import ConfigurationError


def _make_entry(
    *,
    stage=DeletionStage.TRASHED,
    entity_type="budget",
    entity_id=None,
    workspace_id=None,
):
    now = datetime.now(timezone.utc)
    return RecycleBinEntry(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        entity_type=entity_type,
        entity_id=entity_id or uuid4(),
        entity_name="Test Entry",
        stage=stage,
        deleted_by=uuid4(),
        deleted_at=now,
        trashed_until=now + timedelta(days=30),
        tombstoned_at=now if stage == DeletionStage.TOMBSTONED else None,
        tombstoned_by=uuid4() if stage == DeletionStage.TOMBSTONED else None,
        tombstoned_until=(now + timedelta(days=30)) if stage == DeletionStage.TOMBSTONED else None,
        snapshot={"name": "Test Entry"},
        cascade_snapshot={},
        restored_at=None,
        restored_by=None,
    )


@pytest.fixture
def store():
    return MagicMock()


@pytest.fixture
def adapter():
    mock = MagicMock()
    mock.entity_type.return_value = "budget"
    mock.soft_delete.return_value = {"name": "Test Budget", "amount": "1000"}
    return mock


@pytest.fixture
def provider(adapter):
    p = SoftDeleteProvider()
    p.register(adapter)
    return p


@pytest.fixture
def policy():
    return RetentionPolicy(trash_retention_days=30, tombstone_retention_days=30)


# ── TrashEntityUseCase ──────────────────────────────────────


class TestTrashEntityUseCase:
    def test_trash_creates_entry(self, store, provider, policy):
        store.find_by_entity.return_value = None
        uc = TrashEntityUseCase(store=store, provider=provider, policy=policy, audit_log=MagicMock())

        cmd = TrashCommand(
            workspace_id=uuid4(),
            entity_type="budget",
            entity_id=uuid4(),
            deleted_by=uuid4(),
        )
        entry = uc.execute(cmd)

        assert entry.stage == DeletionStage.TRASHED
        assert entry.entity_type == "budget"
        assert entry.snapshot["name"] == "Test Budget"
        store.save.assert_called_once()

    def test_trash_raises_if_already_trashed(self, store, provider, policy):
        store.find_by_entity.return_value = _make_entry()
        uc = TrashEntityUseCase(store=store, provider=provider, policy=policy, audit_log=MagicMock())

        cmd = TrashCommand(
            workspace_id=uuid4(),
            entity_type="budget",
            entity_id=uuid4(),
            deleted_by=uuid4(),
        )
        with pytest.raises(EntityAlreadyTrashedError):
            uc.execute(cmd)

    def test_trash_computes_trashed_until(self, store, provider, policy):
        store.find_by_entity.return_value = None
        uc = TrashEntityUseCase(store=store, provider=provider, policy=policy, audit_log=MagicMock())

        cmd = TrashCommand(
            workspace_id=uuid4(),
            entity_type="budget",
            entity_id=uuid4(),
            deleted_by=uuid4(),
        )
        entry = uc.execute(cmd)
        assert entry.trashed_until > entry.deleted_at
        delta = entry.trashed_until - entry.deleted_at
        assert delta.days == 30


# ── RestoreEntityUseCase ────────────────────────────────────


class TestRestoreEntityUseCase:
    def test_restore_from_trashed(self, store, provider):
        entry = _make_entry(stage=DeletionStage.TRASHED)
        store.find_by_id.return_value = entry
        uc = RestoreEntityUseCase(store=store, provider=provider, audit_log=MagicMock())

        cmd = RestoreCommand(entry_id=entry.id, restored_by=uuid4())
        result = uc.execute(cmd)

        assert result.restored_at is not None
        assert result.restored_by == cmd.restored_by
        store.delete.assert_called_once_with(entry.id)

    def test_restore_from_tombstoned_raises(self, store, provider):
        entry = _make_entry(stage=DeletionStage.TOMBSTONED)
        store.find_by_id.return_value = entry
        uc = RestoreEntityUseCase(store=store, provider=provider, audit_log=MagicMock())

        cmd = RestoreCommand(entry_id=entry.id, restored_by=uuid4())
        with pytest.raises(EntryNotRestorableError):
            uc.execute(cmd)

    def test_restore_not_found_raises(self, store, provider):
        store.find_by_id.return_value = None
        uc = RestoreEntityUseCase(store=store, provider=provider, audit_log=MagicMock())

        cmd = RestoreCommand(entry_id=uuid4(), restored_by=uuid4())
        with pytest.raises(EntryNotFoundError):
            uc.execute(cmd)


# ── EmptyBinUseCase ─────────────────────────────────────────


class TestEmptyBinUseCase:
    def test_empty_bin_tombstones_all_entries(self, store, provider, policy, adapter):
        ws_id = uuid4()
        entries = [_make_entry(workspace_id=ws_id) for _ in range(3)]
        store.list_for_workspace.return_value = entries
        uc = EmptyBinUseCase(store=store, provider=provider, policy=policy, audit_log=MagicMock())

        count = uc.execute(ws_id, uuid4())

        assert count == 3
        assert adapter.hard_delete.call_count == 3
        assert store.save.call_count == 3

        # Verify saved entries are TOMBSTONED
        for call in store.save.call_args_list:
            saved_entry = call[0][0]
            assert saved_entry.stage == DeletionStage.TOMBSTONED
            assert saved_entry.tombstoned_at is not None

    def test_empty_bin_with_no_entries(self, store, provider, policy):
        store.list_for_workspace.return_value = []
        uc = EmptyBinUseCase(store=store, provider=provider, policy=policy, audit_log=MagicMock())

        count = uc.execute(uuid4(), uuid4())
        assert count == 0


# ── PurgeExpiredUseCase ─────────────────────────────────────


class TestPurgeExpiredUseCase:
    def test_tombstone_expired_trash(self, store, provider, policy, adapter):
        entries = [_make_entry() for _ in range(2)]
        store.find_expired_trashed.return_value = entries
        audit = MagicMock()
        uc = PurgeExpiredUseCase(store=store, provider=provider, policy=policy, audit_log=audit)

        count = uc.tombstone_expired_trash(datetime.now(timezone.utc))

        assert count == 2
        assert adapter.hard_delete.call_count == 2
        assert store.save.call_count == 2

    def test_purge_expired_tombstones(self, store, provider, policy):
        entries = [_make_entry(stage=DeletionStage.TOMBSTONED) for _ in range(2)]
        store.find_expired_tombstoned.return_value = entries
        audit = MagicMock()
        uc = PurgeExpiredUseCase(store=store, provider=provider, policy=policy, audit_log=audit)

        count = uc.purge_expired_tombstones(datetime.now(timezone.utc))

        assert count == 2
        assert store.delete.call_count == 2
        assert audit.log_purge.call_count == 2

    def test_purge_with_no_expired(self, store, provider, policy):
        store.find_expired_tombstoned.return_value = []
        audit = MagicMock()
        uc = PurgeExpiredUseCase(store=store, provider=provider, policy=policy, audit_log=audit)

        count = uc.purge_expired_tombstones(datetime.now(timezone.utc))
        assert count == 0
        audit.log_purge.assert_not_called()


# ── SoftDeleteProvider ──────────────────────────────────────


class TestSoftDeleteProvider:
    def test_register_and_get(self):
        adapter = MagicMock()
        adapter.entity_type.return_value = "transaction"

        provider = SoftDeleteProvider()
        provider.register(adapter)
        assert provider.get_adapter("transaction") is adapter

    def test_get_unknown_raises(self):
        provider = SoftDeleteProvider()
        with pytest.raises(
            ConfigurationError,
            match="No SoftDeletePort adapter registered for entity type: nonexistent",
        ):
            provider.get_adapter("nonexistent")

    def test_supported_types(self):
        a1 = MagicMock()
        a1.entity_type.return_value = "budget"
        a2 = MagicMock()
        a2.entity_type.return_value = "transaction"

        provider = SoftDeleteProvider()
        provider.register(a1)
        provider.register(a2)
        assert sorted(provider.supported_types()) == ["budget", "transaction"]
