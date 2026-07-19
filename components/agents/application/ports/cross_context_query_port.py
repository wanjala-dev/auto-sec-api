"""
Ports for cross-context queries the agents bounded context needs.

Instead of importing models from identity, project, workspace, or team
persistence layers, the agents service asks through these ports.  Each
port is implemented by an ORM adapter in ``infrastructure/adapters/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class WorkspaceQueryPort(ABC):
    """Read-only workspace lookups needed by the agents context."""

    @abstractmethod
    def get_by_id(self, workspace_id: str) -> Optional[Any]:
        """Return a workspace or *None*."""

    @abstractmethod
    def exists(self, workspace_id: str) -> bool:
        """Check workspace existence without fetching the full object."""


class TeamQueryPort(ABC):
    """Read-only team lookups needed by the agents context."""

    @abstractmethod
    def get_by_id(self, team_id: str, *, active_only: bool = True) -> Optional[Any]:
        """Return a team or *None*."""


class ProjectQueryPort(ABC):
    """Read-only project/column lookups needed by action-to-task conversion."""

    @abstractmethod
    def get_project_by_id(self, project_id: str, *, team: Any) -> Optional[Any]:
        """Return a project or *None*."""

    @abstractmethod
    def get_column_by_id(self, column_id: str, *, team: Any) -> Optional[Any]:
        """Return a column or *None*."""

    @abstractmethod
    def list_columns(self, *, team: Any, workspace: Any, active_only: bool = True) -> Any:
        """Return columns for a team/workspace pair."""


class UserQueryPort(ABC):
    """Read-only user lookups."""

    @abstractmethod
    def get_by_ids(self, user_ids: list[str]) -> list[Any]:
        """Return users matching the given IDs."""


class FileRepositoryPort(ABC):
    """File status management for document/PDF conversations."""

    @abstractmethod
    def get_by_id(self, file_id: str, *, owner: Any) -> Any:
        """Return a file owned by *owner*.  Raises on not-found."""

    @abstractmethod
    def update_processing_status(self, file: Any, *, status: str) -> None:
        """Persist a file's processing_status change."""


class DocumentQueryPort(ABC):
    """Read-only access to AI documents and their chunks."""

    @abstractmethod
    def get_with_chunks(self, document_id: str) -> Optional[Any]:
        """Return a document with ordered chunks pre-fetched, or *None*."""
