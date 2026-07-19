"""Port for agent persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.agents.domain.entities.agent_entity import AgentEntity


class AgentRepositoryPort(ABC):

    @abstractmethod
    def find_by_id(self, agent_id: UUID) -> AgentEntity | None: ...

    @abstractmethod
    def list_by_user(
        self,
        user_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> list[AgentEntity]: ...

    @abstractmethod
    def list_by_workspace(self, workspace_id: UUID) -> list[AgentEntity]: ...

    @abstractmethod
    def update_status(self, agent_id: UUID, new_status: str) -> AgentEntity: ...
