"""Application service for the recycle_bin bounded context.

Orchestration only -- delegates to use cases. Single front door for
all recycle bin operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.recycle_bin.application.commands.restore_command import RestoreCommand
from components.recycle_bin.application.commands.trash_command import TrashCommand
from components.recycle_bin.application.ports.audit_log_port import AuditLogPort
from components.recycle_bin.application.ports.recycle_bin_store_port import RecycleBinStorePort
from components.recycle_bin.application.providers.soft_delete_provider import SoftDeleteProvider
from components.recycle_bin.application.use_cases.empty_bin_use_case import EmptyBinUseCase
from components.recycle_bin.application.use_cases.purge_expired_use_case import PurgeExpiredUseCase
from components.recycle_bin.application.use_cases.restore_entity_use_case import RestoreEntityUseCase
from components.recycle_bin.application.use_cases.trash_entity_use_case import TrashEntityUseCase
from components.recycle_bin.domain.entities.recycle_bin_entry_entity import RecycleBinEntry
from components.recycle_bin.domain.enums import DeletionStage
from components.recycle_bin.domain.errors import EntryNotFoundError
from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy


@dataclass
class RecycleBinService:
    store: RecycleBinStorePort
    provider: SoftDeleteProvider
    audit_log: AuditLogPort
    policy: RetentionPolicy = field(default_factory=RetentionPolicy)

    # ── Commands ────────────────────────────────────────────────

    def trash(self, command: TrashCommand) -> RecycleBinEntry:
        use_case = TrashEntityUseCase(
            store=self.store,
            provider=self.provider,
            policy=self.policy,
            audit_log=self.audit_log,
        )
        return use_case.execute(command)

    def restore(self, command: RestoreCommand) -> RecycleBinEntry:
        use_case = RestoreEntityUseCase(
            store=self.store,
            provider=self.provider,
            audit_log=self.audit_log,
        )
        return use_case.execute(command)

    def empty_bin(self, workspace_id: UUID, emptied_by: UUID, reason: str = "") -> int:
        use_case = EmptyBinUseCase(
            store=self.store,
            provider=self.provider,
            policy=self.policy,
            audit_log=self.audit_log,
        )
        return use_case.execute(workspace_id, emptied_by, reason=reason)

    def permanently_delete_one(
        self, entry_id: UUID, deleted_by: UUID, reason: str = ""
    ) -> None:
        entry = self.store.find_by_id(entry_id)
        if entry is None:
            raise EntryNotFoundError(entry_id)

        # If still trashed, hard-delete the original row first
        if entry.stage == DeletionStage.TRASHED:
            adapter = self.provider.get_adapter(entry.entity_type)
            adapter.hard_delete(entry.entity_id)

        self.audit_log.log_purge(
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            workspace_id=entry.workspace_id,
            actor_id=deleted_by,
            reason=reason,
        )
        self.store.delete(entry.id)

    # ── Queries ─────────────────────────────────────────────────

    def list_bin(
        self,
        workspace_id: UUID,
        stage: DeletionStage | None = None,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RecycleBinEntry]:
        return self.store.list_for_workspace(
            workspace_id, stage=stage, entity_type=entity_type, limit=limit, offset=offset
        )

    def count_bin(self, workspace_id: UUID, stage: DeletionStage | None = None) -> int:
        return self.store.count_for_workspace(workspace_id, stage=stage)
