"""Cross-context repository ports for LangChain tool data access.

These ports abstract the ORM queries that tool functions currently
perform directly.  Infrastructure adapters (``OrmProjectToolRepository``,
etc.) implement these interfaces so that tools depend only on the port,
not on Django models.

Graca's Explicit Architecture: dependencies always point *inward* —
tools live in infrastructure, ports in the application/ports ring.

Usage in a tool function::

    class ProjectTool(BaseTool):
        project_repo: ProjectToolRepository  # injected by AIProvider

        def _run(self, query: str) -> str:
            projects = self.project_repo.list_for_workspace(workspace_id)
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

# ──────────────────────────────────────────────────────────────────────
# Project / Task domain
# ──────────────────────────────────────────────────────────────────────


class ProjectToolRepository(ABC):
    """Read/write port for projects used by tools."""

    @abstractmethod
    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        team_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_by_id(self, project_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def create(self, *, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]: ...


class TaskToolRepository(ABC):
    """Read/write port for tasks used by tools."""

    @abstractmethod
    def list_for_workspace(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        assignee_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_by_id(self, task_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def create(self, *, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def update(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def add_comment(self, *, task_id: str, author_id: str, content: str) -> dict[str, Any]: ...

    @abstractmethod
    def list_columns(self, project_id: str) -> list[dict[str, Any]]: ...


# ──────────────────────────────────────────────────────────────────────
# Workspace domain
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# Workspace domain
# ──────────────────────────────────────────────────────────────────────


class WorkspaceToolRepository(ABC):
    """Read port for workspace metadata used by tools."""

    @abstractmethod
    def get_by_id(self, workspace_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_members(self, workspace_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_teams(self, workspace_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_categories(self, workspace_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_tags(self, workspace_id: str) -> list[dict[str, Any]]: ...


# ──────────────────────────────────────────────────────────────────────
# Content / News domain
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# User / Permission domain
# ──────────────────────────────────────────────────────────────────────


class UserToolRepository(ABC):
    """Read port for user data used by tools."""

    @abstractmethod
    def get_by_id(self, user_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def search(
        self,
        workspace_id: str,
        *,
        query: str | None = None,
    ) -> list[dict[str, Any]]: ...


class PermissionToolRepository(ABC):
    """Read port for AI permission checks used by tools."""

    @abstractmethod
    def can_perform(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        action: str,
        scope_type: str = "workspace",
        scope_id: str | None = None,
    ) -> bool: ...
