"""Port for persisting and retrieving session memory (extracted facts).

Adapters may store facts in the database, a vector store, or a file.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.agents.domain.services.session_memory_extractor import (
    ExtractedFact,
    SessionMemory,
)


class SessionMemoryPort(ABC):
    """Abstract contract for session memory persistence."""

    @abstractmethod
    def load(self, workspace_id: str, agent_type: str) -> SessionMemory:
        """Load all stored facts for a workspace + agent type."""
        ...

    @abstractmethod
    def save_facts(
        self,
        workspace_id: str,
        agent_type: str,
        facts: list[ExtractedFact],
    ) -> None:
        """Append new facts (deduplicates against existing)."""
        ...

    @abstractmethod
    def clear(self, workspace_id: str, agent_type: str) -> None:
        """Remove all stored facts for a workspace + agent type."""
        ...
