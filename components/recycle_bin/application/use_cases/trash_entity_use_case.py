from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from components.recycle_bin.application.commands.trash_command import TrashCommand
from components.recycle_bin.application.ports.audit_log_port import AuditLogPort
from components.recycle_bin.application.ports.recycle_bin_store_port import RecycleBinStorePort
from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.errors import EntityAlreadyTrashedError
from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy

logger = logging.getLogger(__name__)


@dataclass
class TrashEntityUseCase:
    store: RecycleBinStorePort
    provider: SoftDeleteProvider
    policy: RetentionPolicy
    audit_log: AuditLogPort

    def execute(self, command: TrashCommand) -> RecycleBinEntry:
        # Guard: entity already in the bin
        existing = self.store.find_by_entity(command.entity_type, command.entity_id)
        if existing is not None:
            raise EntityAlreadyTrashedError(command.entity_type, command.entity_id)

        started = time.monotonic()
        adapter = self.provider.get_adapter(command.entity_type)
        snapshot = adapter.soft_delete(command.entity_id)

        now = datetime.now(timezone.utc)
        entry = RecycleBinEntry(
            id=uuid4(),
            workspace_id=command.workspace_id,
            entity_type=command.entity_type,
            entity_id=command.entity_id,
            entity_name=snapshot.get("name", str(command.entity_id)),
            stage=DeletionStage.TRASHED,
            deleted_by=command.deleted_by,
            deleted_at=now,
            trashed_until=self.policy.trashed_until(now),
            tombstoned_at=None,
            tombstoned_by=None,
            tombstoned_until=None,
            snapshot=snapshot,
            cascade_snapshot={},
            restored_at=None,
            restored_by=None,
        )
        self.store.save(entry)
        # Audit AFTER the row is committed to the bin — if save fails
        # we don't want a phantom audit entry for something that
        # didn't actually get trashed. Audit failure itself is
        # swallowed by the adapter so it can't undo the user-facing
        # action.
        self.audit_log.log_trash(
            entity_type=command.entity_type,
            entity_id=command.entity_id,
            workspace_id=command.workspace_id,
            actor_id=command.deleted_by,
            reason=command.reason,
        )
        # Grep target: 'recycle_bin_trashed'.
        logger.info(
            "recycle_bin_trashed entity_type=%s entity_id=%s workspace_id=%s "
            "deleted_by=%s entry_id=%s duration_ms=%d",
            command.entity_type,
            command.entity_id,
            command.workspace_id,
            command.deleted_by,
            entry.id,
            int((time.monotonic() - started) * 1000),
        )
        return entry
