"""Tool repository registry — provides repository instances to tool functions.

Instead of importing ORM models directly, tool functions should access
data through this registry::

    from components.agents.infrastructure.adapters.langchain.tools._repos import repos

    def list_budgets(agent, ...) -> str:
        budgets = repos.budget.list_for_workspace(agent.workspace_id)
        ...

This is a transitional service locator.  The long-term goal is full
constructor injection via LangChain tool classes that receive repository
ports in their ``__init__``.  This module enables incremental migration
of the 13 tool files without a big-bang rewrite.

All repository instances are module-level singletons (stateless, so safe
to share across threads).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.agents.application.ports.tool_data_port import (
    PermissionToolRepository,
    ProjectToolRepository,
    TaskToolRepository,
    UserToolRepository,
    WorkspaceToolRepository,
)


@dataclass
class ToolRepositoryRegistry:
    """Holds all tool data repository instances.

    Lazily initialized on first access to avoid import-order issues
    with Django app readiness.
    """

    _project: ProjectToolRepository | None = field(default=None, repr=False)
    _task: TaskToolRepository | None = field(default=None, repr=False)
    _workspace: WorkspaceToolRepository | None = field(default=None, repr=False)
    _user: UserToolRepository | None = field(default=None, repr=False)
    _permission: PermissionToolRepository | None = field(default=None, repr=False)

    def _ensure_loaded(self) -> None:
        """Lazy-load all ORM adapters on first property access."""
        if self._project is not None:
            return
        from components.agents.infrastructure.repositories.tool_data_repository import (
            OrmPermissionToolRepository,
            OrmProjectToolRepository,
            OrmTaskToolRepository,
            OrmUserToolRepository,
            OrmWorkspaceToolRepository,
        )

        self._project = OrmProjectToolRepository()
        self._task = OrmTaskToolRepository()
        self._workspace = OrmWorkspaceToolRepository()
        self._user = OrmUserToolRepository()
        self._permission = OrmPermissionToolRepository()

    @property
    def project(self) -> ProjectToolRepository:
        self._ensure_loaded()
        return self._project  # type: ignore[return-value]

    @property
    def task(self) -> TaskToolRepository:
        self._ensure_loaded()
        return self._task  # type: ignore[return-value]

    @property
    def workspace(self) -> WorkspaceToolRepository:
        self._ensure_loaded()
        return self._workspace  # type: ignore[return-value]

    @property
    def user(self) -> UserToolRepository:
        self._ensure_loaded()
        return self._user  # type: ignore[return-value]

    @property
    def permission(self) -> PermissionToolRepository:
        self._ensure_loaded()
        return self._permission  # type: ignore[return-value]


# Module-level singleton — stateless, thread-safe.
repos = ToolRepositoryRegistry()
