from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from components.recycle_bin.application.ports.audit_log_port import AuditLogPort
from components.recycle_bin.application.ports.recycle_bin_store_port import RecycleBinStorePort
from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy


_DEFAULT_EMPTY_REASON = "Recycle bin emptied"


@dataclass
class EmptyBinUseCase:
    store: RecycleBinStorePort
    provider: SoftDeleteProvider
    policy: RetentionPolicy
    audit_log: AuditLogPort

    def execute(
        self, workspace_id: UUID, emptied_by: UUID, reason: str = ""
    ) -> int:
        entries = self.store.list_for_workspace(workspace_id, stage=DeletionStage.TRASHED, limit=1000)
        now = datetime.now(timezone.utc)
        count = 0
        # Empty-bin emits one audit row per entry so the per-entity
        # history page still shows the purge event when an admin
        # opens it later. The supplied reason (or a sane default) is
        # attached to every row so the bulk action's intent is
        # preserved on every affected entity.
        audit_reason = reason or _DEFAULT_EMPTY_REASON

        for entry in entries:
            adapter = self.provider.get_adapter(entry.entity_type)
            adapter.hard_delete(entry.entity_id)

            tombstoned_entry = dataclasses.replace(
                entry,
                stage=DeletionStage.TOMBSTONED,
                tombstoned_at=now,
                tombstoned_by=emptied_by,
                tombstoned_until=self.policy.tombstoned_until(now),
            )
            self.store.save(tombstoned_entry)
            self.audit_log.log_purge(
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                workspace_id=entry.workspace_id,
                actor_id=emptied_by,
                reason=audit_reason,
            )
            count += 1

        return count
