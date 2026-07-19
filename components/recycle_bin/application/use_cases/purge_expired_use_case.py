from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from components.recycle_bin.application.ports.audit_log_port import AuditLogPort
from components.recycle_bin.application.ports.recycle_bin_store_port import RecycleBinStorePort
from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy


@dataclass
class PurgeExpiredUseCase:
    store: RecycleBinStorePort
    provider: SoftDeleteProvider
    policy: RetentionPolicy
    audit_log: AuditLogPort

    def tombstone_expired_trash(self, now: datetime) -> int:
        """Move expired TRASHED entries to TOMBSTONED (hard-delete originals)."""
        entries = self.store.find_expired_trashed(now)
        count = 0

        for entry in entries:
            adapter = self.provider.get_adapter(entry.entity_type)
            adapter.hard_delete(entry.entity_id)

            tombstoned_entry = dataclasses.replace(
                entry,
                stage=DeletionStage.TOMBSTONED,
                tombstoned_at=now,
                tombstoned_until=self.policy.tombstoned_until(now),
            )
            self.store.save(tombstoned_entry)
            count += 1

        return count

    def purge_expired_tombstones(self, now: datetime) -> int:
        """Permanently delete expired TOMBSTONED bin entries and audit-log each purge."""
        entries = self.store.find_expired_tombstoned(now)
        count = 0

        for entry in entries:
            self.audit_log.log_purge(
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                workspace_id=entry.workspace_id,
                purged_by="system",
            )
            self.store.delete(entry.id)
            count += 1

        return count
