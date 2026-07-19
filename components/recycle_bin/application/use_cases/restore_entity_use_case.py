from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from components.recycle_bin.application.commands.restore_command import RestoreCommand
from components.recycle_bin.application.ports.audit_log_port import AuditLogPort
from components.recycle_bin.application.ports.recycle_bin_store_port import RecycleBinStorePort
from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.errors import EntryNotFoundError, EntryNotRestorableError


@dataclass
class RestoreEntityUseCase:
    store: RecycleBinStorePort
    provider: SoftDeleteProvider
    audit_log: AuditLogPort

    def execute(self, command: RestoreCommand) -> RecycleBinEntry:
        entry = self.store.find_by_id(command.entry_id)
        if entry is None:
            raise EntryNotFoundError(command.entry_id)

        if entry.stage == DeletionStage.TOMBSTONED:
            raise EntryNotRestorableError(command.entry_id, entry.stage)

        adapter = self.provider.get_adapter(entry.entity_type)
        adapter.restore(entry.entity_id)

        now = datetime.now(timezone.utc)
        restored_entry = RecycleBinEntry(
            id=entry.id,
            workspace_id=entry.workspace_id,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            entity_name=entry.entity_name,
            stage=entry.stage,
            deleted_by=entry.deleted_by,
            deleted_at=entry.deleted_at,
            trashed_until=entry.trashed_until,
            tombstoned_at=entry.tombstoned_at,
            tombstoned_by=entry.tombstoned_by,
            tombstoned_until=entry.tombstoned_until,
            snapshot=entry.snapshot,
            cascade_snapshot=entry.cascade_snapshot,
            restored_at=now,
            restored_by=command.restored_by,
        )

        self.store.delete(entry.id)
        # Audit the restore so the entity's history page shows it
        # alongside any prior trash + later edits. Reason is whatever
        # the UI captured (empty string is fine).
        self.audit_log.log_restore(
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            workspace_id=entry.workspace_id,
            actor_id=command.restored_by,
            reason=command.reason,
        )
        return restored_entry
