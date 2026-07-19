"""Port: fetch raw workspace facts for the snapshot builder.

Keeps the snapshot-building domain pure — infrastructure reads the ORM
and hands the domain a plain dataclass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.knowledge.domain.value_objects.workspace_snapshot import (
    WorkspaceSnapshotInput,
)


class WorkspaceSnapshotDataPort(ABC):
    """Loads the data the snapshot builder needs, without domain touching the ORM."""

    @abstractmethod
    def load(self, workspace_id: str) -> WorkspaceSnapshotInput | None:
        """Return the input dataclass for *workspace_id*, or ``None`` if missing."""
        ...
