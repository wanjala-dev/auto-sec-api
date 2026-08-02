"""
Ports for cross-context queries the agents bounded context needs.

Instead of importing models from identity, project, workspace, or team
persistence layers, the agents service asks through these ports.  Each
port is implemented by an ORM adapter in ``infrastructure/adapters/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceAiToggleStatus:
    """The non-secret AI-toggle facts the kill-switch report reads off a workspace.

    Carries exactly the two things ``ai_governance_service.kill_switch_status``
    needs: whether the workspace row exists at all (``found``) and the value of
    ``Workspace.ai_teammate_enabled`` (the workspace-level AI switch the
    entitlement gate, the chat gate and the detector fan-out all read). No other
    workspace field crosses the boundary.
    """

    found: bool
    ai_teammate_enabled: bool


class WorkspaceQueryPort(ABC):
    """Read-only workspace lookups needed by the agents context."""

    @abstractmethod
    def get_by_id(self, workspace_id: str) -> Any | None:
        """Return a workspace or *None*."""

    @abstractmethod
    def exists(self, workspace_id: str) -> bool:
        """Check workspace existence without fetching the full object."""

    @abstractmethod
    def get_ai_toggle_status(self, workspace_id: str) -> WorkspaceAiToggleStatus:
        """Return the workspace's AI-toggle status for the kill-switch report.

        Resolves the row through the model's **base** manager (unfiltered), so an
        inactive/soft-deleted workspace is still *found* and its
        ``ai_teammate_enabled`` still read — the kill-switch report must reflect a
        halted/inactive workspace, not silently treat it as absent. A missing row
        (or a read failure) yields ``found=False, ai_teammate_enabled=False``.
        """


class TeamQueryPort(ABC):
    """Read-only team lookups needed by the agents context."""

    @abstractmethod
    def get_by_id(self, team_id: str, *, active_only: bool = True) -> Any | None:
        """Return a team or *None*."""


class ProjectQueryPort(ABC):
    """Read-only project/column lookups needed by action-to-task conversion."""

    @abstractmethod
    def get_project_by_id(self, project_id: str, *, team: Any) -> Any | None:
        """Return a project or *None*."""

    @abstractmethod
    def get_column_by_id(self, column_id: str, *, team: Any) -> Any | None:
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
    def get_with_chunks(self, document_id: str) -> Any | None:
        """Return a document with ordered chunks pre-fetched, or *None*."""
