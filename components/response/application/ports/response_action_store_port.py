"""Port: persist + read back response-action executions (the reversibility ledger)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.response.domain.entities.response_action_entity import ResponseActionExecution


class ResponseActionStorePort(ABC):
    @abstractmethod
    def save(self, action: ResponseActionExecution) -> ResponseActionExecution:
        """Insert or update; returns the persisted entity."""

    @abstractmethod
    def get(self, action_id: UUID, *, workspace_id: UUID) -> ResponseActionExecution | None:
        """Load one action scoped to its workspace (tenant isolation)."""

    @abstractmethod
    def list_for_workspace(
        self, workspace_id: UUID, *, status: str | None = None, limit: int = 50
    ) -> list[ResponseActionExecution]:
        """Most-recent-first; optionally filtered to one lifecycle status."""
