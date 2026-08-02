"""RemediationService — the remediation context's single application front door.

Callers (the trigger wiring, a future retrieval-at-triage step, any read
surface) go through this, never the individual use cases or adapters. It exposes
exactly one *write*: ``record`` — the gated entry path. There is deliberately no
other create method, because ``RecordRemediationEntryUseCase`` is the sole writer
of the corpus (ADR 0012 D1). Reads are workspace-scoped.
"""

from __future__ import annotations

from uuid import UUID

from components.remediation.application.commands.record_remediation_entry_command import (
    RecordRemediationEntryCommand,
)
from components.remediation.application.use_cases.record_remediation_entry_use_case import (
    RecordRemediationEntryUseCase,
)
from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry


class RemediationService:
    def __init__(
        self,
        *,
        record: RecordRemediationEntryUseCase,
        store,
    ) -> None:
        self._record = record
        self._store = store

    def record(self, command: RecordRemediationEntryCommand) -> RemediationEntry:
        """Attempt to admit a candidate fix into the corpus. Raises
        ``EntryGateNotSatisfiedError`` (writing nothing) unless the D1 gate's
        three conditions all hold."""
        return self._record.execute(command)

    def get(self, *, entry_id: UUID, workspace_id: UUID) -> RemediationEntry | None:
        return self._store.get(entry_id, workspace_id=workspace_id)

    def list_for_workspace(self, *, workspace_id: UUID, limit: int = 50) -> list[RemediationEntry]:
        return self._store.list_for_workspace(workspace_id, limit=limit)
