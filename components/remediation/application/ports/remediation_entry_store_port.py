"""Port: persist + read back RemediationEntry rows (the vetted corpus).

Every read is workspace-scoped — the tenant boundary (ADR 0012 D4) is a
mandatory argument, not an optional filter, so a caller cannot accidentally
retrieve across workspaces. ``save`` is the *only* persistence entry point, and
it is reached only from the gated use case.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry


class RemediationEntryStorePort(ABC):
    @abstractmethod
    def save(self, entry: RemediationEntry) -> RemediationEntry:
        """Insert or update; returns the persisted entity."""

    @abstractmethod
    def get(self, entry_id: UUID, *, workspace_id: UUID) -> RemediationEntry | None:
        """Load one entry scoped to its workspace (tenant isolation)."""

    @abstractmethod
    def find_by_finding_task(self, *, workspace_id: UUID, finding_task_id: str) -> RemediationEntry | None:
        """Return the (single) active entry for a finding/task in a workspace, if
        one already cleared the gate — used for idempotency (one entry per fix)."""

    @abstractmethod
    def list_for_workspace(self, workspace_id: UUID, *, limit: int = 50) -> list[RemediationEntry]:
        """The active (non-revoked) corpus for a workspace, newest-first. Never
        crosses a workspace boundary (D4)."""
